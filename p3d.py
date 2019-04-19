import tensorflow as tf
from network import *
# from settings import *
CROP_SIZE=112  
NUM_FRAMES_PER_CLIP=16  #clip length
BATCH_SIZE=12
RGB_CHANNEL=3
BLOCK_EXPANSION=4  #You do not need change

def get_conv_weight(name,kshape,wd=0.0005):
    with tf.device('/cpu:0'):
        var=tf.get_variable(name,shape=kshape,initializer=tf.contrib.layers.xavier_initializer())
    if wd!=0:
        weight_decay = tf.nn.l2_loss(var)*wd
        tf.add_to_collection('weightdecay_losses', weight_decay)
    return var

def convS(name,l_input,in_channels,out_channels):
    return tf.nn.bias_add(tf.nn.conv3d(l_input,get_conv_weight(name=name,
                                                               kshape=[1,3,3,in_channels,out_channels]),
                                                               strides=[1,1,1,1,1],padding='SAME'),
                                              get_conv_weight(name+'_bias',[out_channels],0))
def convT(name,l_input,in_channels,out_channels):
    return tf.nn.bias_add(tf.nn.conv3d(l_input,get_conv_weight(name=name,
                                                               kshape=[3,1,1,in_channels,out_channels]),
                                                               strides=[1,1,1,1,1],padding='SAME'),
                                              get_conv_weight(name+'_bias',[out_channels],0))

#build the bottleneck struction of each block.
class Bottleneck():
    def __init__(self,l_input,inplanes,planes,stride=1,downsample='', training=True, n_s=0,depth_3d=47):
        
        self.X_input=l_input
        self.downsample=downsample
        self.planes=planes
        self.inplanes=inplanes
        self.depth_3d=depth_3d
        self.ST_struc=('A','B','C')
        self.len_ST=len(self.ST_struc)
        self.id=n_s
        self.n_s=n_s
        self.ST=list(self.ST_struc)[self.id % self.len_ST]
        self.stride_p=[1,1,1,1,1]
        self.training = training
        if self.downsample!='':
            self.stride_p=[1,1,2,2,1]
        if n_s<self.depth_3d:
            if n_s==0:
                self.stride_p=[1,1,1,1,1]
        else:
            if n_s==self.depth_3d:
                self.stride_p=[1,2,2,2,1]
            else:
                self.stride_p=[1,1,1,1,1]
    #P3D has three types of bottleneck sub-structions.
    def ST_A(self,name,x):
        x=convS(name+'_S',x,self.planes,self.planes)
        x=tf.layers.batch_normalization(x,training=self.training)
        x=tf.nn.relu(x)
        x=convT(name+'_T',x,self.planes,self.planes)
        x=tf.layers.batch_normalization(x,training=self.training)
        x=tf.nn.relu(x)
        return x
    
    def ST_B(self,name,x):
        tmp_x=convS(name+'_S',x,self.planes,self.planes)
        tmp_x=tf.layers.batch_normalization(tmp_x,training=self.training)
        tmp_x=tf.nn.relu(tmp_x)
        x=convT(name+'_T',x,self.planes,self.planes)
        x=tf.layers.batch_normalization(x,training=self.training)
        x=tf.nn.relu(x)
        return x+tmp_x
    
    def ST_C(self,name,x):
        x=convS(name+'_S',x,self.planes,self.planes)
        x=tf.layers.batch_normalization(x,training=self.training)
        x=tf.nn.relu(x)
        tmp_x=convT(name+'_T',x,self.planes,self.planes)
        tmp_x=tf.layers.batch_normalization(tmp_x,training=self.training)
        tmp_x=tf.nn.relu(tmp_x)
        return x+tmp_x
    
    def infer(self):
        residual=self.X_input
        if self.n_s<self.depth_3d:
            out=tf.nn.conv3d(self.X_input,get_conv_weight('conv3_{}_1'.format(self.id),[1,1,1,self.inplanes,self.planes]),
                             strides=self.stride_p,padding='SAME')
            out=tf.layers.batch_normalization(out,training=self.training)
            
        else:
            param=self.stride_p
            param.pop(1)
            out=tf.nn.conv2d(self.X_input,get_conv_weight('conv2_{}_1'.format(self.id),[1,1,self.inplanes,self.planes]),
                             strides=param,padding='SAME')
            out=tf.layers.batch_normalization(out,training=self.training)
    
        out=tf.nn.relu(out)    
        if self.id<self.depth_3d:
            if self.ST=='A':
                out=self.ST_A('STA_{}_2'.format(self.id),out)
            elif self.ST=='B':
                out=self.ST_B('STB_{}_2'.format(self.id),out)
            elif self.ST=='C':
                out=self.ST_C('STC_{}_2'.format(self.id),out)
        else:
            out=tf.nn.conv2d(out,get_conv_weight('conv2_{}_2'.format(self.id),[3,3,self.planes,self.planes]),
                                  strides=[1,1,1,1],padding='SAME')
            out=tf.layers.batch_normalization(out,training=self.training)
            out=tf.nn.relu(out)

        if self.n_s<self.depth_3d:
            out=tf.nn.conv3d(out,get_conv_weight('conv3_{}_3'.format(self.id),[1,1,1,self.planes,self.planes*BLOCK_EXPANSION]),
                             strides=[1,1,1,1,1],padding='SAME')
            out=tf.layers.batch_normalization(out,training=self.training)
        else:
            out=tf.nn.conv2d(out,get_conv_weight('conv2_{}_3'.format(self.id),[1,1,self.planes,self.planes*BLOCK_EXPANSION]),
                             strides=[1,1,1,1],padding='SAME')
            out=tf.layers.batch_normalization(out,training=self.training)
           
        if len(self.downsample)==1:
            residual=tf.nn.conv2d(residual,get_conv_weight('dw2d_{}'.format(self.id),[1,1,self.inplanes,self.planes*BLOCK_EXPANSION]),
                                  strides=[1,2,2,1],padding='SAME')
            residual=tf.layers.batch_normalization(residual,training=self.training)
        elif len(self.downsample)==2:
            residual=tf.nn.conv3d(residual,get_conv_weight('dw3d_{}'.format(self.id),[1,1,1,self.inplanes,self.planes*BLOCK_EXPANSION]),
                                  strides=self.downsample[1],padding='SAME')
            residual=tf.layers.batch_normalization(residual,training=self.training)
        
        residual = attention(residual, ch=None, name='attention_{}'.format(self.id))
        # CBAM
        # residual = cbam_block(residual, name='attention_{}'.format(self.id))
        out+=residual
        out=tf.nn.relu(out)
        
        return out

#build a singe block of p3d,depth_3d=47 means p3d-199
class make_block():
    def __init__(self,_X,planes,num,inplanes,cnt,training=True, depth_3d=47,stride=1):
        self.input=_X
        self.planes=planes
        self.inplanes=inplanes
        self.num=num
        self.cnt=cnt
        self.depth_3d=depth_3d
        self.stride=stride
        self.training=training
        if self.cnt<depth_3d:
            if self.cnt==0:
                stride_p=[1,1,1,1,1]
            else:
                stride_p=[1,1,2,2,1]
            if stride!=1 or inplanes!=planes*BLOCK_EXPANSION:
                self.downsample=['3d',stride_p]
        else:
            if stride!=1 or inplanes!=planes*BLOCK_EXPANSION:
                self.downsample=['2d']
    def infer(self):
        x=Bottleneck(self.input,self.inplanes,self.planes,self.stride,self.downsample,training=self.training, n_s=self.cnt,depth_3d=self.depth_3d).infer()
        self.cnt+=1
        self.inplanes=BLOCK_EXPANSION*self.planes
        for i in range(1,self.num):
            x=Bottleneck(x,self.inplanes,self.planes,training=self.training, n_s=self.cnt,depth_3d=self.depth_3d).infer()
            self.cnt+=1
        return x

#build structure of the p3d network.
def inference_p3d(_X,_dropout,batch_size=2, training=True):
    cnt=0
    # 16 112 112 3
    conv1_custom=tf.nn.conv3d(_X,get_conv_weight('firstconv1',[1,7,7,3,64]),strides=[1,1,2,2,1],padding='SAME')
    conv1_custom_bn=tf.layers.batch_normalization(conv1_custom,training=training)
    conv1_custom_bn_relu=tf.nn.relu(conv1_custom_bn)
    # 16 56 56 64
    pool1=tf.nn.max_pool3d(conv1_custom_bn_relu,[1,2,3,3,1],strides=[1,2,2,2,1],padding='SAME')
    # 8 28 28 64
    b1=make_block(pool1,64,3,64,cnt)
    res1=b1.infer()
    # 8 28 28 256
    cnt=b1.cnt
    pool2=tf.nn.max_pool3d(res1,[1,2,1,1,1],strides=[1,2,1,1,1],padding='SAME')
    # 4 28 28 256
    b2=make_block(pool2,128,8,256,cnt,stride=2)
    res2=b2.infer()
    # 4 14 14 512 
    cnt=b2.cnt
    pool3=tf.nn.max_pool3d(res2,[1,2,1,1,1],strides=[1,2,1,1,1],padding='SAME')
    # 2 14 14 512
    b3=make_block(pool3,256,36,512,cnt,stride=2)
    res3=b3.infer()
    # 2 7 7 1024
    cnt=b3.cnt
    pool4=tf.nn.max_pool3d(res3,[1,2,1,1,1],strides=[1,2,1,1,1],padding='SAME')
    # 1 7 7 1024
    ###
    ### Deconvoltuion
    ###
    deconv1 = tf.layers.conv3d_transpose(pool4, 512, [1, 3, 3], [2, 2, 2], 'same')
    deconv1_bn = tf.layers.batch_normalization(deconv1, name='deconv1_bn', training=training)
    deconv1_re = tf.nn.relu(deconv1_bn)
    deconv1_concat = tf.concat([deconv1_re, pool3], axis=-1)
    # 2 14 14
    deconv2 = tf.layers.conv3d_transpose(deconv1_concat, 256, [2, 3, 3], [2, 2, 2], 'same')
    deconv2_bn = tf.layers.batch_normalization(deconv2, name='deconv2_bn', training=training)
    deconv2_re = tf.nn.relu(deconv2_bn)
    deconv2_concat = tf.concat([deconv2_re, pool2], axis=-1)
    deconv2_concat = tf.layers.dropout(deconv2_concat, rate=_dropout, training=training)
    # 4 28 28
    deconv3 = tf.layers.conv3d_transpose(deconv2_concat, 128, 3, [2, 2, 2], 'same')
    deconv3_bn = tf.layers.batch_normalization(deconv3, name='deconv3_bn', training=training)
    deconv3_re = tf.nn.relu(deconv3_bn)
    deconv3_drop = tf.layers.dropout(deconv3_re, rate=_dropout, training=training)
    # 8 56 56
    results = tf.layers.conv3d_transpose(deconv3_drop, 1, 3, [2, 2, 2], 'same')
    # convlution
    return results

def inference_p3d_sa(_X,_dropout,batch_size=2, training=True):
    cnt=0
    # 16 112 112 3
    conv1_custom=tf.nn.conv3d(_X,get_conv_weight('firstconv1',[1,7,7,3,64]),strides=[1,1,2,2,1],padding='SAME')
    conv1_custom_bn=tf.layers.batch_normalization(conv1_custom,training=training)
    conv1_custom_bn_relu=tf.nn.relu(conv1_custom_bn)
    # 16 56 56 64
    pool1=tf.nn.max_pool3d(conv1_custom_bn_relu,[1,2,3,3,1],strides=[1,2,2,2,1],padding='SAME')
    # 8 28 28 64
    b1=make_block(pool1,64,3,64,cnt)
    res1=b1.infer()
    # 8 28 28 256
    cnt=b1.cnt
    pool2=tf.nn.max_pool3d(res1,[1,2,1,1,1],strides=[1,2,1,1,1],padding='SAME')
    # 4 28 28 256
    b2=make_block(pool2,128,8,256,cnt,stride=2)
    res2=b2.infer()
    # 4 14 14 512 
    cnt=b2.cnt
    pool3=tf.nn.max_pool3d(res2,[1,2,1,1,1],strides=[1,2,1,1,1],padding='SAME')
    # 2 14 14 512
    b3=make_block(pool3,256,36,512,cnt,stride=2)
    res3=b3.infer()
    # 2 7 7 1024
    cnt=b3.cnt
    pool4=tf.nn.max_pool3d(res3,[1,2,1,1,1],strides=[1,2,1,1,1],padding='SAME')
    # 1 7 7 1024

    ## attention 
    sa_1 = attention(pool4, 1024, 'sa_1', False)
    ###
    ### Deconvoltuion
    ###
    deconv1 = tf.layers.conv3d_transpose(sa_1, 512, [1, 3, 3], [2, 2, 2], 'same')
    deconv1_bn = tf.layers.batch_normalization(deconv1, name='deconv1_bn', training=training)
    deconv1_re = tf.nn.relu(deconv1_bn)
    deconv1_concat = tf.concat([deconv1_re, pool3], axis=-1)
    ## attention 
    sa_2 = attention(deconv1_concat, 1024, 'sa_2', False)
    # 2 14 14
    deconv2 = tf.layers.conv3d_transpose(sa_2, 256, [2, 3, 3], [2, 2, 2], 'same')
    deconv2_bn = tf.layers.batch_normalization(deconv2, name='deconv2_bn', training=training)
    deconv2_re = tf.nn.relu(deconv2_bn)
    deconv2_concat = tf.concat([deconv2_re, pool2], axis=-1)
    ## attention 
    sa_3 = attention(deconv2_concat, 512, 'sa_3', False)
    # 4 28 28
    deconv3 = tf.layers.conv3d_transpose(sa_3, 128, 3, [2, 2, 2], 'same')
    deconv3_bn = tf.layers.batch_normalization(deconv3, name='deconv3_bn', training=training)
    deconv3_re = tf.nn.relu(deconv3_bn)
    # sa_4 = attention(deconv3_re, 128, 'sa_4', False)
    sa_4_drop = tf.layers.dropout(deconv3_re, rate=_dropout, training=training)
    # 8 56 56
    results = tf.layers.conv3d_transpose(sa_4_drop, 1, 3, [2, 2, 2], 'same')
    # 16 112 112
    return results
    