import json,numpy as np,torch
from pathlib import Path
from face_utils import mask_mouth, load_face_crop, extract_inner
from inference import load_model
dev=torch.device('cuda');root=Path('/work/data')
keep=torch.from_numpy(mask_mouth(np.ones((144,144,3),np.uint8)).transpose(2,0,1).astype(np.float32)).to(dev)
base=torch.from_numpy(extract_inner(load_face_crop(str(root/'base.jpg'),str(root/'base.lms'))).transpose(2,0,1).copy()).float().to(dev)/255
def acc(x,m):  # mean |second difference| inside mouth mask
    a=np.abs(x[2:]-2*x[1:-1]+x[:-2]).mean(-1)
    return float((a*m[1:-1]).sum()/m[1:-1].sum())
res={}
for e in [50,60,70,75,100,125,150]:
    net=load_model(f'/work/checkpoints/epoch_{e}.pth',dev);row={}
    for clip in ['speech_12','speech_36']:
        d=root/clip;gt=np.load(d/'crops.npy').astype(np.float32);m=np.load(d/'masks.npy').reshape(len(gt),144,144).astype(np.float32)
        w=np.load(d/'stream_windows.npy')[0];w=np.concatenate([w,np.zeros((len(w),7,2,1024),np.float16)],1).astype(np.float32)
        ps=[]
        with torch.inference_mode():
            for i in range(0,len(gt),16):
                t=torch.from_numpy(gt[i:i+16].transpose(0,3,1,2).copy()).to(dev)/255
                a=torch.from_numpy(w[i:i+16]).to(dev).reshape(-1,40,1024)
                ps.append(net(torch.cat([base[None].expand(len(t),-1,-1,-1),t*keep],1),a).cpu().numpy().transpose(0,2,3,1)*255)
        p=np.concatenate(ps);row[clip]=round(acc(p,m)/acc(gt,m),3)
    res[e]=row;print(e,row,flush=True)
