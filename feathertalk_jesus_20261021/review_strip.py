import json,numpy as np,torch,cv2
from pathlib import Path
from face_utils import mask_mouth, load_face_crop, extract_inner
from inference import load_model
dev=torch.device('cuda');root=Path('/work/data')
keep=torch.from_numpy(mask_mouth(np.ones((144,144,3),np.uint8)).transpose(2,0,1).astype(np.float32)).to(dev)
base=torch.from_numpy(extract_inner(load_face_crop(str(root/'base.jpg'),str(root/'base.lms'))).transpose(2,0,1).copy()).float().to(dev)/255
for clip in ['speech_12','speech_36']:
    d=root/clip;gt=np.load(d/'crops.npy');w=np.load(d/'stream_windows.npy')[0]
    w=np.concatenate([w,np.zeros((len(w),7,2,1024),np.float16)],1).astype(np.float32)
    idx=np.arange(30,230,5)[:20]
    rows=[np.concatenate([cv2.resize(gt[i][40:,:],(96,70)) for i in idx],1)]
    labels=['real']
    for e in [50,60,75,150]:
        net=load_model(f'/work/checkpoints/epoch_{e}.pth',dev)
        with torch.inference_mode():
            t=torch.from_numpy(gt[idx].transpose(0,3,1,2).copy()).float().to(dev)/255
            a=torch.from_numpy(w[idx]).to(dev).reshape(-1,40,1024)
            p=(net(torch.cat([base[None].expand(len(t),-1,-1,-1),t*keep],1),a).cpu().numpy().transpose(0,2,3,1)*255).clip(0,255).astype(np.uint8)
        rows.append(np.concatenate([cv2.resize(x[40:,:],(96,70)) for x in p],1));labels.append(f'ep{e}')
    for r,l in zip(rows,labels):cv2.putText(r,l,(3,12),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,255,255),1)
    cv2.imwrite(f'/work/output/strip_{clip}.jpg',np.concatenate(rows))
print('ok')
