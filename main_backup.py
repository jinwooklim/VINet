# python2.7
import os
import torch 
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F
import torch.utils.data
import torch.optim as optim

from tensorboardX import SummaryWriter

import os
from utils import tools
from utils import se3qua

import FlowNetC


from PIL import Image
import numpy as np

import flowlib

from PIL import Image

import csv
import time


class SE3Comp(nn.Module):
    def __init__(self):
        super(SE3Comp, self).__init__()
        self.threshold_square = 1e-1
        self.threshold_cube = 1e-1
    
    def forward(self, Tg, xi):
        """
        Tg: <Torch.tensor> SE(3) R^7 (x, y, z, ww, wx, wy, wz)
            Tg = torch.zeros(batchSize, 7, 1)
        xi: <Torch.tensor> se(3) R^6 (rho1, rho2, rho3, omega_x, omega_y, omega_z)
            xi_vec = torch.zeros(batchSize, 6, 1)
        return Composed SE(3) in R^7 format
        """
        assert isinstance(Tg, type(torch.zeros(1))),'Tg with wrong datatype, should be torch.Tensor'
        assert isinstance(xi, type(torch.zeros(1))),'Tg with wrong datatype, should be torch.Tensor'

        
        rho   = xi[:, 0:3]
        omega = xi[:, 3:6] #torch.Size([batchSize, 3, 1])
        batchSize = xi.size()[0]
        
        R, V = self.so3_RV(torch.squeeze(omega))
        Txi = torch.zeros(batchSize,4,4)
        Txi[:, 0:3, 0:3] = R
        Txi[:, 3,3] = 1.0
        Txi[:, 0:3, 3] = torch.squeeze(torch.bmm(V, rho))
        
        Tg_matrix = torch.zeros(batchSize,4,4)
        Tg_matrix[:, 3, 3] = 1.0
        q = Tg[:, 3:7]
        Tg_matrix[:, 0:3, 0:3] = self.q_to_Matrix(q)
        Tg_matrix[:, 0, 3] = torch.squeeze(Tg[:, 0])
        Tg_matrix[:, 1, 3] = torch.squeeze(Tg[:, 1])
        Tg_matrix[:, 2, 3] = torch.squeeze(Tg[:, 2])
        T_combine_M = torch.bmm(Txi, Tg_matrix)
        
        return self.batchMtoR7(T_combine_M)
    
    def batchMtoR7(self,M):
        batchSize = M.size()[0]
        cat = None
        for i in range(batchSize):
            a = self.MtoR7(M[i])
            if i == 0:
                cat = torch.unsqueeze(a, dim=0)
                continue
            cat = torch.cat([cat,torch.unsqueeze(a, dim=0)])
            
        return cat
    
    def MtoR7(self,M):#no batch
        R7 = torch.zeros(7,1)
        #print(M[0,3].size())
        #print(R7[0].size())
        R7[0] = M[ 0, 3] # [2] to [2, 1]
        R7[1] = M[ 1, 3] # [2] to [2, 1]
        R7[2] = M[ 2, 3] # [2] to [2, 1]
        #https://d3cw3dd2w32x2b.cloudfront.net/wp-content/uploads/2015/01/matrix-to-quat.pdf
        t = 0
        if M[2, 2] < 0:
            if M[0, 0] > M[1, 1]:#
                t = 1 + M[0, 0] - M[1, 1] - M[2, 2]
                q = [M[2, 1]-M[1, 2],  t,  M[0, 1]+M[1, 0],  M[2, 0]+M[0, 2]]
            else:#
                t = 1 - M[0, 0] + M[1, 1] - M[2, 2]
                q = [M[0, 2]-M[2, 0],  M[0, 1]+M[1, 0],  t,  M[1, 2]+M[2, 1]]
        else:
            if M[0, 0] < -M[1, 1]:#
                t = 1 - M[0, 0] - M[1, 1] + M[2, 2]
                q = [M[1, 0]-M[0, 1],  M[2, 0]+M[0, 2],  M[1, 2]+M[2, 1],  t]
            else:#
                t = 1 + M[0, 0] + M[1, 1] + M[2, 2]
                q = [t,  M[2, 1]-M[1, 2],  M[0, 2]-M[2, 0],  M[1, 0]-M[0, 1]]
        R7[3], R7[4], R7[5], R7[6] = q
        R7[3] *= 0.5 / torch.sqrt(t)
        R7[4] *= 0.5 / torch.sqrt(t)
        R7[5] *= 0.5 / torch.sqrt(t)
        R7[6] *= 0.5 / torch.sqrt(t)
        if R7[3] < 0:
            R7[3] *= -1
            R7[4] *= -1
            R7[5] *= -1
            R7[6] *= -1
        return R7
        
    def q_to_Matrix(self, q):
        qw = q[:, 0]
        qx = q[:, 1]
        qy = q[:, 2]
        qz = q[:, 3]
        M = torch.zeros(q.size()[0], 3, 3)

        M[:, 0, 0] = torch.squeeze( 1 - 2*torch.mul(qy,qy) - 2*torch.mul(qz,qz) )
        M[:, 1, 0] = torch.squeeze( 2*torch.mul(qx,qy) + 2*torch.mul(qz,qw) )
        M[:, 2, 0] = torch.squeeze( 2*torch.mul(qx,qz) - 2*torch.mul(qy,qw) )

        M[:, 0, 1] = torch.squeeze( 2*torch.mul(qx,qy) - 2*torch.mul(qz,qw) )
        M[:, 1, 1] = torch.squeeze( 1 - 2*torch.mul(qx,qx) - 2*torch.mul(qz,qz) )
        M[:, 2, 1] = torch.squeeze( 2*torch.mul(qy,qz) + 2*torch.mul(qx,qw) )

        M[:, 0, 2] = torch.squeeze( 2*torch.mul(qx,qz) + 2*torch.mul(qy,qw) )
        M[:, 1, 2] = torch.squeeze( 2*torch.mul(qy,qz) - 2*torch.mul(qx,qw) )
        M[:, 2, 2] = torch.squeeze( 1 - 2*torch.mul(qx,qx) - 2*torch.mul(qy,qy) )
    
        return M
    
    def so3_RV(self, omega):
        """
        (3-tuple)
        omega = torch.zeros(batchSize, 3)

        return batchx3x3 matrix R after exponential mapping, V
        """
        batchSize = omega.size()[0]
        omega_x = omega[:, 0]
        omega_y = omega[:, 1]
        omega_z = omega[:, 2]

        #paramIndex = paramIndex + 3
        omega_skew = torch.zeros(batchSize,3,3)
        """
        0    -oz  oy  0
        oz   0   -ox  0
        -oy  ox   0   0
        0    0    0   0
        """
        omega_skew[:, 1, 0] = omega_z.clone()
        omega_skew[:, 2, 0] = -1 * omega_y

        omega_skew[:, 0, 1] = -1 * omega_z
        omega_skew[:, 2, 1] = omega_x.clone()

        omega_skew[:, 0, 2] = omega_y.clone()
        omega_skew[:, 1, 2] = -1 * omega_x

        omega_skew_sqr = torch.bmm(omega_skew,omega_skew)
        theta_sqr = torch.pow(omega_x,2) +\
                    torch.pow(omega_y,2) +\
                    torch.pow(omega_z,2)
        theta = torch.pow(theta_sqr,0.5)
        theta_cube = torch.mul(theta_sqr, theta)#
        sin_theta = torch.sin(theta)
        sin_theta_div_theta = torch.div(sin_theta,theta)
        sin_theta_div_theta[sin_theta_div_theta != sin_theta_div_theta] = 0 # set nan to zero

        one_minus_cos_theta = torch.ones(theta.size()) - torch.cos(theta)
        one_minus_cos_div_theta_sqr = torch.div(one_minus_cos_theta,theta_sqr)

        theta_minus_sin_theta = theta - torch.sin(theta)
        theta_minus_sin_div_theta_cube = torch.div(theta_minus_sin_theta, theta_cube)

        sin_theta_div_theta_tensor            = torch.ones(omega_skew.size())
        one_minus_cos_div_theta_sqr_tensor    = torch.ones(omega_skew.size())
        theta_minus_sin_div_theta_cube_tensor = torch.ones(omega_skew.size())
        
        # sin_theta_div_theta do not need linear approximation
        sin_theta_div_theta_tensor = sin_theta_div_theta
        #print(sin_theta_div_theta_tensor)
        for b in range(batchSize):
            if theta_sqr[b] > self.threshold_square:
                one_minus_cos_div_theta_sqr_tensor[b] = one_minus_cos_div_theta_sqr[b]
            elif theta_sqr[b] < 1e-6:
                one_minus_cos_div_theta_sqr_tensor[b] = 0#0.5
            else:#Taylor expansion
                c = 1.0 / 2.0
                c += theta[b]**(4*1) / 720.0#np.math.factorial(6) 
                c += theta[b]**(4*2) / 3628800.0#np.math.factorial(6+4) 
                c -= theta[b]**(2) / 24.0#np.math.factorial(4) 
                c -= theta[b]**(2 + 4) / 40320.0#np.math.factorial(4+4) 
                one_minus_cos_div_theta_sqr_tensor[b] = c
                
            if theta_cube[b] > self.threshold_cube:
                theta_minus_sin_div_theta_cube_tensor[b] = theta_minus_sin_div_theta_cube[b]
            elif theta_sqr[b] < 1e-6:
                theta_minus_sin_div_theta_cube_tensor[b] = 0#1.0 / 6.0
            else:#Taylor expansion
                s = 1.0 / 6.0
                s += theta[b]**(4*1) / 5040.0
                s += theta[b]**(4*2) / 39916800.0
                s -= theta[b]**(2) / 120.0
                s -= theta[b]**(2 + 4) / 362880.0
                theta_minus_sin_div_theta_cube_tensor[b] = s

        completeTransformation = torch.zeros(batchSize,3,3)

        completeTransformation[:, 0, 0] += 1
        completeTransformation[:, 1, 1] += 1
        completeTransformation[:, 2, 2] += 1   

        sin_theta_div_theta_tensor = torch.unsqueeze(sin_theta_div_theta_tensor, dim=1)
        completeTransformation = completeTransformation +\
            self.vecMulMat(sin_theta_div_theta_tensor,omega_skew) +\
            torch.mul(one_minus_cos_div_theta_sqr_tensor, omega_skew_sqr)


        V = torch.zeros(batchSize,3,3)    
        V[:, 0, 0] += 1
        V[:, 1, 1] += 1
        V[:, 2, 2] += 1 
        V = V + torch.mul(one_minus_cos_div_theta_sqr_tensor, omega_skew) +\
            torch.mul(theta_minus_sin_div_theta_cube_tensor, omega_skew_sqr)
        return completeTransformation, V
    
    def vecMulMat(self, vec, mat):
        mat_view = mat.view(vec.size()[0], -1)
        out = mat_view * vec
        return out.view(mat_view.size()[0], mat.size()[1], -1)


class MyDataset:
    
    def __init__(self, base_dir, sequence):
        self.base_dir = base_dir
        self.sequence = sequence
        self.base_path_img = self.base_dir + self.sequence + '/cam0/data/'
        
        
        self.data_files = os.listdir(self.base_dir + self.sequence + '/cam0/data/')
        self.data_files.sort()
        
        ## relative camera pose
        self.trajectory_relative = self.read_R6TrajFile('/vicon0/sampled_relative_R6.csv')
        
		## abosolute camera pose (global)
        self.trajectory_abs = self.readTrajectoryFile('/vicon0/sampled.csv')
        
		## imu
        self.imu = self.readIMU_File('/imu0/data.csv')
        
        self.imu_seq_len = 5
   
    def readTrajectoryFile(self, path):
        traj = []
        with open(self.base_dir + self.sequence + path) as csvfile:
            spamreader = csv.reader(csvfile, delimiter=',', quotechar='|')
            for row in spamreader:
                parsed = [float(row[1]), float(row[2]), float(row[3]), 
                          float(row[4]), float(row[5]), float(row[6]), float(row[7])]
                traj.append(parsed)
                
        return np.array(traj)
    
    def read_R6TrajFile(self, path):
        traj = []
        with open(self.base_dir + self.sequence + path) as csvfile:
            spamreader = csv.reader(csvfile, delimiter=',', quotechar='|')
            for row in spamreader:
                parsed = [float(row[1]), float(row[2]), float(row[3]), 
                          float(row[4]), float(row[5]), float(row[6])]
                traj.append(parsed)
                
        return np.array(traj)
    
    def readIMU_File(self, path):
        imu = []
        count = 0
        with open(self.base_dir + self.sequence + path) as csvfile:
            spamreader = csv.reader(csvfile, delimiter=',', quotechar='|')
            for row in spamreader:
                if count == 0:
                    count += 1
                    continue
                parsed = [float(row[1]), float(row[2]), float(row[3]), 
                          float(row[4]), float(row[5]), float(row[6])]
                imu.append(parsed)
                
        return np.array(imu)

    '''
    def getTrajectoryAbs(self, idx):
        return self.trajectory_abs[idx]
    '''

    def getTrajectoryAbs(self, idx, batch):
        return_list = []
        for b in range(batch):
            batch_first_trajectory = self.trajectory_abs[idx+b]
            return_list.append(batch_first_trajectory)
        return np.asarray(return_list) # (batch, 7, 1)

    def getTrajectoryAbsAll(self):
        return self.trajectory_abs
    
    def getIMU(self):
        return self.imu
    
    def __len__(self):
        return len(self.trajectory_relative)
    
    def load_img_bat(self, idx, batch):
        batch_x = []
        batch_imu =[]
        for i in range(batch):
            print("### batch_idx ###")
            print("img_idx : ", idx+i, idx+1+i)
            x_data_np_1 = np.array(Image.open(self.base_path_img + self.data_files[idx+i]))
            x_data_np_2 = np.array(Image.open(self.base_path_img + self.data_files[idx+1+i]))

            ## 3 channels
            x_data_np_1 = np.array([x_data_np_1, x_data_np_1, x_data_np_1])
            x_data_np_2 = np.array([x_data_np_2, x_data_np_2, x_data_np_2])

            X = np.array([x_data_np_1, x_data_np_2])
            batch_x.append(X)

            print("IMU_idx : ", idx-self.imu_seq_len+1+i, idx+1+i)
            tmp = np.array(self.imu[idx-self.imu_seq_len+i : idx+1+i])
            batch_imu.append(tmp)

            #idx = idx + 1
        
        batch_x = np.array(batch_x)
        batch_imu = np.array(batch_imu)
            
        X = Variable(torch.from_numpy(batch_x).type(torch.FloatTensor).cuda())    
        X2 = Variable(torch.from_numpy(batch_imu).type(torch.FloatTensor).cuda())    

             
        ## F2F gt
        Y = Variable(torch.from_numpy(self.trajectory_relative[idx+1 : idx+1+batch]).type(torch.FloatTensor).cuda())
        Y = Y.view(batch, 6, 1)
        ## global pose gt
        Y2 = Variable(torch.from_numpy(self.trajectory_abs[idx+1 : idx+1+batch]).type(torch.FloatTensor).cuda())
       	Y2 = Y2.view(batch, 7, 1)
        return X, X2, Y, Y2

    
    
class Vinet(nn.Module):
    def __init__(self):
        super(Vinet, self).__init__()
        self.rnn = nn.LSTM(
            input_size=49158, #12301, #49152,#24576, 
            hidden_size=1024,#64, 
            num_layers=1,
            batch_first=True)
        self.rnn.cuda()
        
        self.rnnIMU = nn.LSTM(
            input_size=6, 
            hidden_size=6,
            num_layers=1,
            batch_first=True)
        self.rnnIMU.cuda()
        
        self.linear1 = nn.Linear(1024, 128)
        self.linear2 = nn.Linear(128, 6)
        self.linear1.cuda()
        self.linear2.cuda()
        
        checkpoint = None
        checkpoint_pytorch = '/notebooks/model/FlowNet2-C_checkpoint.pth.tar'
        #checkpoint_pytorch = '/notebooks/data/model/FlowNet2-SD_checkpoint.pth.tar'
        if os.path.isfile(checkpoint_pytorch):
            checkpoint = torch.load(checkpoint_pytorch,\
                                map_location=lambda storage, loc: storage.cuda(0))
            best_err = checkpoint['best_EPE']
        else:
            print('No checkpoint')

        self.flownet_c = FlowNetC.FlowNetC(batchNorm=False)
        self.flownet_c.load_state_dict(checkpoint['state_dict'])
        self.flownet_c.cuda()

    def forward(self, image, imu):
        batch_size, timesteps, C, H, W = image.size() # [batch, timesteps, channel, Height, Width]
         
        ## Input1: Feed image pairs to FlownetC
        ##c_in = image.view(batch_size, timesteps * C, H, W)
        c_in = image.view(batch_size, timesteps * C, H, W)
        c_out = self.flownet_c(c_in)

        ## Input2: Feed IMU records to LSTM
        imu_out, (imu_n, imu_c) = self.rnnIMU(imu)
        #imu_out = imu.view(batch_size, 1, -1)
        imu_out = imu_out[:, -1, :] # (batch, 6)
        #print("imu_out : ", imu_out.shape)
        imu_out = imu_out.unsqueeze(1) # (batch, 1, 6)
        #print("imu_out : ", imu_out.shape)
        
        ## Combine the output of input1 and 2 and feed it to LSTM
        ##r_in = c_out.view(batch_size, timesteps, -1)
        r_in = c_out.view(batch_size, 1, -1) # (batch, timesteps, 49152)
        cat_out = torch.cat((r_in, imu_out), 2) # (batch, timesteps, ?)
        #print("cat_out : ", cat_out.shape)
        
        ## Feed concatenate data to Main LSTM stream
        #print("Main LSTM stream input size : ", cat_out.shape)
        r_out, (h_n, h_c) = self.rnn(cat_out) # r_out : (batch_size, 1, 1024)
        l_out1 = self.linear1(r_out[:,-1,:]) # (batch_size, 128)
        #print("lll_out1 : " , l_out1.shape)
        l_out2 = self.linear2(l_out1) # (batch_size,  6)
        #print("lll_out1 : " , l_out2.shape)
        return l_out2
    
    
def model_out_to_flow_png(output):
    out_np = output[0].data.cpu().numpy()

    #https://gitorchub.com/DediGadot/PatchBatch/blob/master/flowlib.py
    out_np = np.squeeze(out_np)
    out_np = np.moveaxis(out_np,0, -1)

    im_arr = flowlib.flow_to_image(out_np)
    im = Image.fromarray(im_arr)
    im.save('test.png')


def train():
    epoch = 10
    streams = 1
    batch = 4
    model = Vinet()
    se3Layer = SE3Comp()
    #optimizer = optim.SGD(model.parameters(), lr=0.001, momentum=0.9)
    optimizer = optim.Adam(model.parameters(), lr = 0.001)
    
    writer = SummaryWriter()
    
    model.train()

    mydataset = MyDataset('/notebooks/EuRoC_modify/', 'V1_01_easy')
    #criterion  = nn.MSELoss()
    criterion  = nn.L1Loss(size_average=False)
    
    start = 5
    end = len(mydataset)-batch
    batch_num = (end - start) // (batch)
    startT = time.time() 
    abs_traj = None
    
    with tools.TimerBlock("Start training") as block:
        for k in range(epoch):
            #for i in range(start, end, (batch*2)):#len(mydataset)-1):
            for i in range(start, end, (batch)):#len(mydataset)-1):
                data, data_imu, target_f2f, target_global = mydataset.load_img_bat(i, batch)
                data, data_imu, target_f2f, target_global = \
                    data.cuda(), data_imu.cuda(), target_f2f.cuda(), target_global.cuda()

                optimizer.zero_grad()
                
                ## First data for SE3 Composition layer
                if i == start:
                    ## load first SE3 pose xyzQuaternion
                    abs_traj = mydataset.getTrajectoryAbs(start, batch) # (batch, 7)
                    abs_traj_SE3 = np.expand_dims(abs_traj, axis=2) # (batch, 7, 1)
                    abs_traj_SE3 = Variable(torch.from_numpy(abs_traj_SE3).type(torch.FloatTensor).cuda())
    
                ## LSTM part Forward
                se3 = model(data, data_imu) # (batch, 6)
                se3 = se3.unsqueeze(2) # (batch, 6, 1)
                
                ## SE part
                abs_traj = se3Layer(abs_traj_SE3.data.cpu(), se3.data.cpu())
                abs_traj_SE3 = Variable(abs_traj) # (batch, 7, 1)

                ## (F2F loss) + (Global pose loss)
                ## Global pose: Full concatenated pose relative to the start of the sequence
             	## (batch, 6, 1) // (batch, 7, 1)
                loss = criterion(se3.cpu(), target_f2f.cpu()) + criterion(abs_traj_SE3.cpu(), target_global.cpu())

                loss.backward()
                optimizer.step()

                avgTime = block.avg()
                remainingTime = int((batch_num*epoch -  (i + batch_num*k)) * avgTime)
                rTime_str = "{:02d}:{:02d}:{:02d}".format(int(remainingTime/60//60), 
                                                          int(remainingTime//60%60), 
                                                          int(remainingTime%60))

                block.log('Train Epoch: {}\t[{}/{} ({:.0f}%)]\tLoss: {:.6f}, TimeAvg: {:.4f}, Remaining: {}'.format(k, i , batch_num, 100. * (i + batch_num*k) / (batch_num*epoch), loss.data[0], avgTime, rTime_str))
                
                writer.add_scalar('loss', loss.data[0], k*batch_num + i)
                
                check_str = 'checkpoint_{}.pt'.format(k)
                torch.save(model.state_dict(), check_str)
            
    #torch.save(model, 'vinet_v1_01.pt')
    #model.save_state_dict('vinet_v1_01.pt')
    #torch.save(model.state_dict(), 'vinet_v1_01.pt')
    writer.export_scalars_to_json("./all_scalars.json")
    writer.close()


def test():
    #checkpoint_pytorch = '/notebooks/vinet/vinet_v1_01.pt'
    checkpoint_pytorch = '/notebooks/vinet/checkpoint_9.pt'
    if os.path.isfile(checkpoint_pytorch):
        checkpoint = torch.load(checkpoint_pytorch,\
                            map_location=lambda storage, loc: storage.cuda(0))
        #best_err = checkpoint['best_EPE']
    else:
        print('No checkpoint')
    
    batch = 2
    model = Vinet(batch=batch)
    se3Layer = SE3Comp()
    model.load_state_dict(checkpoint)  
    model.cuda()
    model.eval()
    #mydataset = MyDataset('/notebooks/EuRoC_modify/', 'V2_01_easy')
    datapath = "V2_01_easy"
    mydataset = MyDataset('/notebooks/data/', datapath)
    
    err = 0
    ans = []
    abs_traj = None
    start = 5
    #for i in range(start, len(mydataset)-batch):
    for i in range(start, 100):
        data, data_imu, target_f2f, target_global = mydataset.load_img_bat(i, batch)
        data, data_imu, target_f2f, target_global = data.cuda(), data_imu.cuda(), target_f2f.cuda(), target_global.cuda()

        ## First data for SE3 Composition layer
        if i == start:
            ## load first SE3 pose xyzQuaternion
            abs_traj = mydataset.getTrajectoryAbs(start, batch)
            abs_traj_SE3 = np.expand_dims(abs_traj, axis=2) # (x, y, z, w, wx, wy, wz)
            abs_traj_SE3 = Variable(torch.from_numpy(abs_traj_SE3).type(torch.FloatTensor).cuda()) 
                    
        ## LSTM part forward
        se3 = model(data, data_imu) # (v1, v2, v3, v4 ,v5, v6)
        se3 = se3.unsqueeze(2) # (batch, 6, 1)
        
        ## SE part
        abs_traj_SE3 = se3Layer(abs_traj_SE3.data.cpu(), se3.data.cpu())
        abs_traj_SE3 = Variable(abs_traj_SE3) # (batch, 7, 1)
	    
        err += float(((target_f2f - se3) ** 2).mean()) # mean((x-X)^2)
        print(err)
	    ## Convert se3(v1, v2, v3, v4, v5, v6) -> xyzQ
        #xyzq = se3qua.se3R6toxyzQ(se3.data.cpu().numpy())
        #ans.append(xyzq)
        #print('{}/{}'.format(str(i+1), str(len(mydataset)-1)) )
        
    print('Final err = {}'.format(err/(len(mydataset)-1)))  
    #trajectoryAbs = mydataset.getTrajectoryAbsAll()
    #print(trajectoryAbs[0])
    #x = trajectoryAbs[0].astype(str)
    #x = ",".join(x)
    
    #with open('/notebooks/EuRoC_modify/V2_01_easy/vicon0/sampled_relative_ans.csv', 'w+') as f:
    #with open('/notebooks/vinet/%s_sampled_relative_ans.csv'%datapath, 'w') as f:
    #    tmpStr = x
    #    f.write(tmpStr + '\n')        
    #    
    #    for i in range(len(ans)-1):
    #        tmpStr = ans[i].astype(str)
    #        tmpStr = ",".join(tmpStr)
    #        print(tmpStr)
    #        print(type(tmpStr))
    #        f.write(tmpStr + '\n')      
   
    
def main():
    train()
          
    #test()


if __name__ == '__main__':
    main()
