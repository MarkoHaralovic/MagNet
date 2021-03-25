import argparse

class BaseOptions():
    def __init__(self):
        parser = argparse.ArgumentParser(
                formatter_class=argparse.ArgumentDefaultsHelpFormatter)

        # Dataset config
        parser.add_argument('--dataset', required=True, type=str, help='dataset name: cityscapes, deepglobe, gleason')
        parser.add_argument('--root', required=True, type=str, help='path to images for training and testing')
        parser.add_argument('--datalist', required=True, type=str, help='path to .txt containing image and label path')
        parser.add_argument('--scales', required=True, type=str, help='scales: w1-h1,w2-h2,... , e.g. 512-512,1024-1024,2048-2048')
        parser.add_argument('--crop_size', required=True, metavar='N', nargs="+", type=int, help='crop size, e.g. 256 128')
        parser.add_argument('--input_size', required=True, metavar='N', nargs="+", type=int, help='input size, e.g. 256 128')
        parser.add_argument('--num_workers', default=1, type=int, help="number of workers for dataloader")

        # Model config
        parser.add_argument('--model', required=True, type=str, help='model name: fpn')
        parser.add_argument('--num_classes', required=True, type=int, help='number of classes')
        parser.add_argument('--pretrained', type=str, help='pretrained weight')
        parser.add_argument('--pretrained_refinement', type=str, help='pretrained refinement module')
        self.parser = parser

    def parse(self):
        args = self.parser.parse_args()

        # Parse scales
        args.scales = [tuple(int(x) for x in s.split("-")) for s in args.scales.split(",")]
        
        args.crop_size = tuple(args.crop_size)
        args.input_size = tuple(args.input_size)

        return args