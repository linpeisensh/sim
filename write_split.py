import os
data_path = 'E:/dataset/sequences'
for i in range(11):
    seq_path = os.path.join(data_path, "{:02d}/image_2".format(i))
    sub_path = os.listdir(seq_path)
    f_name = './splits/odom/test_files_{:02d}.txt'.format(i)
    n = len(sub_path)
    if not os.path.exists(f_name):
        with open(f_name, 'w') as f:
            f.writelines('{} {} l\n'.format(i,j) for j in range(1,n-1))
        f.close()
