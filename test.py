import os
import math
import time

from tqdm import tqdm

import numpy as np
import cv2

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision.ops import roi_align
from torchvision.transforms.functional import to_pil_image

from magnet.options.test import TestOptions
from magnet.dataset import get_dataset_with_name
from magnet.model import get_model_with_name
from magnet.model.refinement import RefinementMagNet
from magnet.utils.geometry import get_patch_coords, calculate_uncertainty, get_uncertain_point_coords_on_grid, point_sample, ensemble
from magnet.utils.blur import GaussianBlur, MedianBlur
from magnet.utils.metrics import get_mean_iou, confusion_matrix, get_freq_iou, get_overall_iou

@torch.no_grad()
def get_batch_predictions(model, sub_batch_size, patches, another=None):

    preds = []
    n_patches = patches.shape[0]
    n_batches = math.ceil(n_patches/sub_batch_size)
    for batch_idx in range(n_batches):
        max_index = min((batch_idx + 1) * sub_batch_size, n_patches)
        batch = patches[batch_idx * sub_batch_size: max_index]
        with torch.no_grad():
            if another is None:
                preds += [torch.softmax(model(batch), dim=1)]
            else:
                preds += [torch.softmax(model(batch, another[batch_idx * sub_batch_size: max_index]), dim=1)]
    preds = torch.cat(preds, dim=0)
    return preds

@torch.no_grad()
def main():

    # Parse arguments
    opt = TestOptions().parse()

    sub_batch_size = opt.sub_batch_size

    device = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")

    # Create dataset
    dataset = get_dataset_with_name(opt.dataset)(opt)
    dataloader = DataLoader(dataset, batch_size=1, shuffle=False, num_workers=opt.num_workers)

    # Create model
    model = get_model_with_name(opt.model)(opt.num_classes).to(device)
    refinement_model = RefinementMagNet(opt.num_classes, use_bn=True).to(device)
    
    # Load pretrained weights for backbone
    state_dict = torch.load(opt.pretrained)
    model.load_state_dict(state_dict)
    _ = model.eval()

    # Load pretrained weights for refinement module
    state_dict = torch.load(opt.pretrained_refinement)
    refinement_model.load_state_dict(state_dict, strict=False)
    _ = refinement_model.eval()

    # Patch coords
    patch_coords = []
    for scale in opt.scales:
        patch_coords += [torch.tensor(get_patch_coords(scale, opt.crop_size)).to(device)]

    # Allocate prediction map
    C, H, W = opt.num_classes, opt.scales[-1][1], opt.scales[-1][0]
    final_output = None

    # Blur function
    median_blur = MedianBlur(channel=1, kernel_size=(opt.smooth_kernel, opt.smooth_kernel)).to(device)
    median_blur.eval()

    conf_mat = np.zeros((opt.num_classes, opt.num_classes), dtype=np.float)
    refined_conf_mat = np.zeros((opt.num_classes, opt.num_classes), dtype=np.float)
    
    # Test dataloader
    pbar = tqdm(total=len(dataset), ascii=True)
    for idx, data in enumerate(dataloader):
        
        pbar.update(1)
        execution_time = {}
        description = ""

        image_patches = data["image_patches"][0]
        scale_idx = data["scale_idx"][0]
        label = data["label"].numpy()

        total_time = time.time()
        eval_time = 0
        coarse_pred = None

        # Refine from coarse-to-fine
        for idx, (ratios, scale) in enumerate(zip(patch_coords, opt.scales)):
            
            # If the first scale, get the prediction only
            if idx == 0:
                
                # Get prediction 
                final_output = get_batch_predictions(model, 1, image_patches[0:1].to(device))
                
                coarse_pred = final_output.clone()
                continue
            if opt.n_patches == 1:
                continue
            coords = ratios.clone()
            coords[:, 0] = coords[:, 0] * final_output.shape[3]
            coords[:, 1] = coords[:, 1] * final_output.shape[2]
            coords[:, 2] = coords[:, 2] * final_output.shape[3]
            coords[:, 3] = coords[:, 3] * final_output.shape[2]

            # Calculate uncertainty
            uncertainty = calculate_uncertainty(final_output)
            patch_uncertainty = roi_align(uncertainty, [coords], output_size=(opt.input_size[1], opt.input_size[0]))
            patch_uncertainty = patch_uncertainty.mean((1,2,3))

            # Choose patches with highest mean uncertainty
            start_time = time.time()
            _, selected_patch_ids = torch.sort(patch_uncertainty)

            del patch_uncertainty

            if opt.n_patches != -1:
                selected_patch_ids = selected_patch_ids[:opt.n_patches]

            # Filter image_patches of this scale
            scale_image_patches = image_patches[scale_idx == idx]
            
            # Filter image_patches with selected_patch_ids
            scale_image_patches = scale_image_patches[selected_patch_ids]

            # Get early predictions
            scale_early_preds = get_batch_predictions(model, sub_batch_size, scale_image_patches.to(device))

            # Get coarse preds (with coords and final_output)
            coarse_preds = roi_align(final_output, [coords[selected_patch_ids]], output_size=(opt.input_size[1], opt.input_size[0]))

            # Refinement
            fine_pred = get_batch_predictions(refinement_model, sub_batch_size, coarse_preds, scale_early_preds)

            del coarse_preds, scale_early_preds

            # Make grids
            selected_ratios = ratios[selected_patch_ids]
            fine_pred, mask = ensemble(fine_pred, selected_ratios, scale)

            # Calculate certainty of fine_pred
            certainty_score = 1.0 - calculate_uncertainty(fine_pred)
            
            if opt.n_patches > 0:
                certainty_score[:,:,mask] = 0.0
            
            uncertainty_score = F.interpolate(uncertainty, scale[::-1], mode='bilinear', align_corners=False)
            error_score = certainty_score * uncertainty_score
            del certainty_score, uncertainty_score
            

            # Smoothing error score
            start_time = time.time()
            _, _, h_e, w_e = error_score.shape
            error_score = F.interpolate(error_score, size=(opt.input_size[1], opt.input_size[0]))
            with torch.no_grad():
                error_score = median_blur(error_score)
            error_score = F.interpolate(error_score, size=(h_e, w_e))
            execution_time["blur"] = execution_time.get("blur", 0) + (time.time() - start_time)
            
            # Get point coordinates
            if opt.n_points > 1.0:
                n_points = min(int(opt.n_points), scale[0] * scale[1] * len(selected_patch_ids) /len(coords))
            else:
                n_points = int(scale[0] * scale[1] * opt.n_points * len(selected_patch_ids) /len(coords))
            
            error_point_indices, error_point_coords = get_uncertain_point_coords_on_grid(error_score, n_points)
            del error_score
            
            error_point_indices = error_point_indices.unsqueeze(1).expand(-1, opt.num_classes, -1)  

            # Get refinement prediction 
            fine_pred = point_sample(fine_pred, error_point_coords, align_corners=False)
            
            if opt.n_patches > 0:
                sample_mask = point_sample(mask.type(torch.float).unsqueeze(0).unsqueeze(0), error_point_coords, align_corners=False).type(torch.bool).squeeze()
            
            final_output = F.interpolate(final_output, scale[::-1], mode='bilinear', align_corners=False)

            if opt.n_patches > 0:
                error_point_indices = error_point_indices[:, :, sample_mask]
                fine_pred = fine_pred[:, :, sample_mask]
                
            final_output = (
                            final_output.reshape(1, opt.num_classes, scale[0] * scale[1])
                            .scatter_(2, error_point_indices, fine_pred)
                            .view(1, opt.num_classes, scale[1], scale[0])
                        )
        
        execution_time["time"] = time.time() - total_time

        # Compute IoU for coarse prediction
        start_time = time.time()
        coarse_pred = F.interpolate(coarse_pred, (H, W), mode='bilinear', align_corners=False).argmax(1).cpu().numpy()
        mat = confusion_matrix(label, coarse_pred, opt.num_classes)
        conf_mat += mat
        description += "Coarse IoU: %.2f, " % (get_freq_iou(mat, opt.dataset)*100)

        # Compute IoU for fine prediction
        final_output = F.interpolate(final_output, (H, W), mode='bilinear', align_corners=False).argmax(1).cpu().numpy()
        mat = confusion_matrix(label, final_output, opt.num_classes)
        refined_conf_mat += mat
        description += "Refinement IoU: %.2f" % (get_freq_iou(mat, opt.dataset)*100)

        if opt.save_pred:
            img = dataset.inverse_transform(image_patches[0])
            img = np.array(to_pil_image(img))[:,:,::-1]

            label = dataset.class2bgr(label[0])
            coarse_pred = dataset.class2bgr(coarse_pred[0])
            fine_pred = dataset.class2bgr(final_output[0])

            h = 512
            w = int((h * 1.0 / img.shape[0]) * img.shape[1])
            save_image = np.zeros((h, w * 4 + 10 * 3, 3), dtype=np.uint8)
            save_image[:,:,2] = 255

            save_image[:, :w] = cv2.resize(img, (h, w))
            save_image[:, w+10: w*2+10] = cv2.resize(label, (h, w))
            save_image[:, w*2+20: w*3+20] = cv2.resize(coarse_pred, (h, w))
            save_image[:, w*3+30:] = cv2.resize(fine_pred, (h, w))
            os.makedirs(opt.save_dir, exist_ok=True)
            cv2.imwrite(os.path.join(opt.save_dir, data["name"][0]), save_image)
        
        description += "".join([", %s: %.2f" % (k, v) for k,v in execution_time.items() if v > 0.01])
        pbar.set_description(description)

    pbar.write("-------SUMMARY-------")
    pbar.write("Coarse IoU: %.2f" % (get_overall_iou(conf_mat, opt.dataset)*100))
    pbar.write("Refinement IoU: %.2f" % (get_overall_iou(refined_conf_mat, opt.dataset)*100))


if __name__ == "__main__":
    main()