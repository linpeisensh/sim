from __future__ import division
import argparse
import numpy as np
from path import Path
from pebble import ProcessPool
import scipy.misc
import sys
from tqdm import tqdm
from collections import Counter
import torch

parser = argparse.ArgumentParser()
parser.add_argument("dataset_dir", metavar='DIR',
                    help='path to original dataset')
parser.add_argument("--dump-root", type=str, default='dump', help="Where to dump the data")
parser.add_argument("--with-depth", action='store_true',
                    help="If available (e.g. with KITTI), will store depth ground truth along with images, for validation")
parser.add_argument("--with-pose", action='store_true',
                    help="If available (e.g. with KITTI), will store pose ground truth along with images, for validation")
parser.add_argument("--height", type=int, default=192, help="image height")
parser.add_argument("--width", type=int, default=640, help="image width")
parser.add_argument("--num-threads", type=int, default=4, help="number of threads to use")

args = parser.parse_args()


class MalagaRawLoader(object):
    def __init__(self,
                 dataset_dir,
                 img_height=192,
                 img_width=640,
                 get_depth=False,
                 get_pose=False):
        self.dataset_dir = Path(dataset_dir)
        self.img_height = img_height
        self.img_width = img_width
        self.get_depth = get_depth
        self.get_pose = get_pose
        # self.cam_ids = ['left', 'right']
        self.cam_ids = ['left']
        self.img_exts = '.jpg'
        self.intrinsics = np.array([[795.11588,   0.00000, 517.12973,   0.00000],
                                    [  0.00000, 795.11588, 395.59665,   0.00000],
                                    [  0.00000,   0.00000,   1.00000,   0.00000],
                                    [  0.00000,   0.00000,   0.00000,   1.00000]], dtype=np.float32)
        self.collect_train_folders()

    def collect_train_folders(self):
        self.scenes = []
        drive_set = sorted(self.dataset_dir.dirs())
        for dr in drive_set:
            self.scenes.append(dr)

    def get_intrinsics(self, zoom_x, zoom_y):
        intrinsics = self.intrinsics
        intrinsics[0] *= zoom_x / self.img_width
        intrinsics[1] *= zoom_y / self.img_height
        return intrinsics

    def collect_scene_data(self, drive):
        train_scenes = []
        for cid in self.cam_ids:
            scene_data = {'cid':cid, 'dir':drive, 'frame_id':[], 'pose':[], 'rel_path':drive.name+'_'+cid}
            img_files = sorted((drive/drive.name+'_rectified_1024x768_Images').files())
            for f in img_files:
                f_name = f.name
                if f_name.split('_')[3] == cid + self.img_exts:
                    scene_data['frame_id'].append(f_name[:-4])
            sample = self.load_image(scene_data, 0)
            if sample is None:
                return []
            
            scene_data['intrinsics'] = self.get_intrinsics(sample[1], sample[2])
            train_scenes.append(scene_data)
        return train_scenes
    
    def get_scene_imgs(self, scene_data):
        def construct_sample(scene_data, i):
            sample = {'img': self.load_image(scene_data, i)[0], 'id':scene_data['frame_id'][i]}
            if self.get_depth:
                sample['depth'] = self.load_depth(scene_data, i)[0]
            if self.get_pose:
                sample['pose'] = scene_data['pose'][i]
            return sample
        
        for (i, frame_id) in enumerate(scene_data['frame_id']):
            yield construct_sample(scene_data, i)

    def load_image(self, scene_data, tgt_idx):
        suf = '_rectified_1024x768_Images'
        img_file = scene_data['dir']/scene_data['dir'].name+suf+'/{}{}'.format(scene_data['frame_id'][tgt_idx], self.img_exts)
        if not img_file.isfile():
            print(img_file)
            print("Img file not found")
            return None
        
        img = scipy.misc.imread(img_file)
        img = self.crop_image(img)
        zoom_y = self.img_height / img.shape[0]
        zoom_x = self.img_width / img.shape[1]
        if zoom_x != 1 and zoom_y != 1:
            # print("img resize")
            img = scipy.misc.imresize(img, (self.img_height, self.img_width))
        return img, zoom_x, zoom_y

    def crop_image(self, image):
        h, w = image.shape[0], image.shape[1]
        bbox_h = [h//2 - self.img_height//2, h//2 + self.img_height//2]
        bbox_w = [w//2 - self.img_width//2, w//2 + self.img_width//2]
        image = image[bbox_h[0]:bbox_h[1], bbox_w[0]:bbox_w[1]]
        # print(image.shape)
        return image


def dump_example(args, scene):
    scene_list = data_loader.collect_scene_data(scene)
    assert len(scene_list) != 0
    for scene_data in scene_list:
        dump_dir = args.dump_root/scene_data['rel_path']

        dump_dir.makedirs_p()
        intrinsics = scene_data['intrinsics']

        dump_cam_file = dump_dir/'cam.txt'

        np.savetxt(dump_cam_file, intrinsics)
        poses_file = dump_dir/'poses.txt'
        poses = []

        idx = 0
        for sample in data_loader.get_scene_imgs(scene_data):
            img = sample["img"]
            dump_img_file = dump_dir/'{:010d}.jpg'.format(idx)
            scipy.misc.imsave(dump_img_file, img)
            if "pose" in sample.keys():
                poses.append(sample["pose"].tolist())
            if "depth" in sample.keys():
                depth_frame_nb = sample["depth_id"]
                dump_depth_file = dump_dir/'{:010d}.npy'.format(idx)
                np.save(dump_depth_file, sample["depth"])
            idx += 1
        if len(poses) != 0:
            np.savetxt(poses_file, np.array(poses).reshape(-1, 12), fmt='%.6e')

        if len(dump_dir.files('*.jpg')) < 3:
            dump_dir.rmtree()

def main():
    args.dump_root = Path(args.dump_root)
    args.dump_root.mkdir_p()

    global data_loader
    data_loader = MalagaRawLoader(args.dataset_dir,
                                    img_height=args.height,
                                    img_width=args.width,
                                    get_depth=args.with_depth,
                                    get_pose=args.with_pose)

    
    n_scenes = len(data_loader.scenes)
    print('Found {} potential scenes'.format(n_scenes))
    print('Retrieving frames')
    if args.num_threads == 1:
        for scene in tqdm(data_loader.scenes):
            dump_example(args, scene)
    else:
        with ProcessPool(max_workers=args.num_threads) as pool:
            tasks = pool.map(dump_example, [args]*n_scenes, data_loader.scenes)
            try:
                for _ in tqdm(tasks.result(), total=n_scenes):
                    pass
            except KeyboardInterrupt as e:
                tasks.cancel()
                raise e

    

if __name__ == '__main__':
    main()