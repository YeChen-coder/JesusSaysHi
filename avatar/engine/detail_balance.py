"""Small CPU ROI filters; original avatar/model assets are never modified."""
import time,json,hashlib,os
from pathlib import Path
import cv2,numpy as np

class DetailBalance:
    def __init__(self,engine):
        self.boxes=engine.bboxes;self.masks=[]
        for index,(x1,y1,x2,y2) in enumerate(self.boxes):
            masks=engine.frame_alphas
            alpha=engine.alpha if masks is None else masks[index]
            mask=cv2.resize(alpha[:,:,0],(int(x2-x1),int(y2-y1)))
            # Do not sharpen the upper part around the nose / cheeks strongly.
            yy=np.linspace(0,1,mask.shape[0])[:,None]
            mask*=np.clip((yy-.22)/.20,0,1)
            self.masks.append(mask)

    def process(self,image,index,kind='sharp'):
        begin=time.perf_counter();x1,y1,x2,y2=map(int,self.boxes[index]);roi=image[y1:y2,x1:x2]
        yuv=cv2.cvtColor(roi,cv2.COLOR_BGR2YCrCb);luma=yuv[:,:,0].astype(np.float32)
        if kind=='sharp':
            detail=luma-cv2.GaussianBlur(luma,(0,0),1.05)
            # Cap enhancement, suppress tiny noise, preserve original chroma.
            delta=np.clip(np.sign(detail)*np.maximum(np.abs(detail)-.6,0)*.70,-8,8)
        elif kind=='soft':
            delta=(cv2.GaussianBlur(luma,(0,0),2.1)-luma)*.80
        else:raise ValueError(kind)
        alpha=self.masks[index]
        yuv[:,:,0]=np.rint(luma+delta*alpha).clip(0,255).astype(np.uint8)
        changed=cv2.cvtColor(yuv,cv2.COLOR_YCrCb2BGR)
        # Preserve exactly every pixel outside the feathered ROI mask.
        selected=alpha>0;roi[selected]=changed[selected]
        return image,(time.perf_counter()-begin)*1000

class IdleAppearance:
    """Reuse original reference frames, overlay only precomputed idle patches."""
    def __init__(self,engine):
        root=engine.assets.detail;self.manifest=json.loads((root/'manifest.json').read_text())
        def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
        expected={'source_base_sha256':engine.manifest['sha256'],
                  'checkpoint_sha256':digest(engine.checkpoint_path),
                  'bboxes_sha256':digest(engine.assets.base/'bboxes.npy'),
                  'patches_sha256':digest(root/'chin_patches.npy'),
                  'idle_video_sha256':digest(root/'idle.mp4')}
        if any(self.manifest.get(k)!=v for k,v in expected.items()):
            raise ValueError('Matched idle assets do not match this base/model; regenerate detail_balance assets')
        self.patches=np.load(root/'chin_patches.npy',mmap_mode='r');self.engine=engine
        if len(self.patches)!=engine.count or self.manifest.get('fps')!=25:
            raise ValueError('Matched idle frame count/fps mismatch')
        self.video_path=root/'idle.mp4';self.poster_path=root/'poster.jpg'

    def frame(self,index):
        image=self.engine.frames[index].copy();x1,y1,x2,y2=map(int,self.engine.bboxes[index])
        image[y1:y2,x1:x2]=self.patches[index,:y2-y1,:x2-x1]
        return image
