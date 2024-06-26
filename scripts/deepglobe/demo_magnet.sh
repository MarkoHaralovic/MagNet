python demo.py --dataset deepglobe \
--image $1 \
--scales 612-612,1224-1224,2448-2448 \
--crop_size 612 612 \
--input_size 508 508 \
--model fpn \
--pretrained checkpoints/deepglobe_fpn.pth \
--pretrained_refinement checkpoints/deepglobe_refinement.pth \
--num_classes 7 \
--n_points 0.75 \
--n_patches -1 \
--sub_batch_size 1 \
--smooth_kernel 11 \
--save_pred \
--save_dir test_results/demo