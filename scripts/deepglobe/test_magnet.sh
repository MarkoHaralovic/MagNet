python test.py --dataset deepglobe \
--root data/deepglobe \
--datalist data/list/deepglobe/val.txt \
--scales 612-612,1224-1224,2448-2448 \
--crop_size 612 612 \
--input_size 508 508 \
--num_workers 8 \
--model fpn \
--pretrained checkpoints/deepglobe_fpn.pth \
--pretrained_refinement checkpoints/deepglobe_refinement.pth \
--num_classes 7 \
--sub_batch_size 3 \
--n_points 0.75 \
--n_patches -1 \
--smooth_kernel 5