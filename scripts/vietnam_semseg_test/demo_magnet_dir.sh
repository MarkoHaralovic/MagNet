IMAGE_DIR="../vietnam_semseg_test/rgb"
OUTPUT_DIR="../vietnam_semseg_test/masks"

start=$(date +%s)


for IMAGE_PATH in $IMAGE_DIR/*; do
    IMAGE_NAME=$(basename $IMAGE_PATH)
    python demo.py --dataset deepglobe \
    --image $IMAGE_PATH \
    --scales 512-512,1024-1024,2048-2048  \
    --crop_size 512 512  \
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
    --save_dir $OUTPUT_DIR
done

end=$(date +%s)

runtime=$((end - start))

echo "MagNet demo runtime: $runtime seconds"
echo "Finished running MagNet demo on all images in $IMAGE_DIR"