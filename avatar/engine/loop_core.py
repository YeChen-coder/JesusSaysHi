"""Moving-base inference. Reuse the same streaming audio and trained weights."""
import json,time,os
from pathlib import Path
import cv2,numpy as np,torch
from stream_core import Engine,Session
from face_utils import crop_face,extract_inner,mask_mouth,reshape_audio_feat,gather_audio_window,FACE_BORDER
from character_assets import character_assets

class LoopEngine(Engine):
    def __init__(self):
        self.teeth=None;self.teeth_mode='model';self.teeth_rows=[]
        self.assets=character_assets()
        self.checkpoint_path=self.assets.checkpoint
        super().__init__(checkpoint=str(self.assets.checkpoint),base_image=self.assets.image,base_landmarks=self.assets.landmarks)
        # MediaPipe owns CPU worker threads; small OpenCV/Torch operations
        # must not fan out across all host cores under the container CPU quota.
        torch.set_num_threads(1);cv2.setNumThreads(1)
        root=self.assets.base
        self.manifest=json.loads((root/'manifest.json').read_text())
        self.frames=np.load(root/'frames.npy',mmap_mode='r')
        self.bboxes=np.load(root/'bboxes.npy')
        self.count=len(self.frames);self.cursor=0;self.indices=[]
        self.crops=np.asarray([crop_face(image,tuple(box)) for image,box in zip(self.frames,self.bboxes)])
        self.references=np.asarray([extract_inner(crop) for crop in self.crops])
        self.masked=np.asarray([mask_mouth(image.copy()) for image in self.references])
        inputs=np.concatenate([self.references.transpose(0,3,1,2),self.masked.transpose(0,3,1,2)],axis=1)
        self.model_inputs=(torch.from_numpy(inputs).to(self.device).float()/255).contiguous()
        # Preserve the native video outside the learned lower-face area. A soft
        # perimeter blends the generated region into the current frame's skin.
        alpha=np.zeros((152,152),np.float32)
        alpha[FACE_BORDER+6:152-FACE_BORDER-6,FACE_BORDER+6:152-FACE_BORDER-6]=1
        self.alpha=cv2.GaussianBlur(alpha,(19,19),4)[...,None]
        self.frame_alphas=None
        self.begin(0)
        # Exercise the actual streaming input sizes using silence, outside
        # session timing. No future test audio is available during this step.
        begin=time.perf_counter()
        with torch.inference_mode():self.visual(self.model_inputs[0:1],torch.zeros(1,40,1024,device=self.device))
        for seconds in [i/10 for i in range(1,52)]+[4.12,4.14,4.52,4.54,5.12,5.14]:
            self.encode(np.zeros(round(seconds*16000),np.float32))
        self.sync();self.stream_shape_warmup_seconds=time.perf_counter()-begin
        if (self.assets.teeth/'manifest.json').exists():
            from teeth_enhance import NewTeethRestorer
            self.teeth=NewTeethRestorer(self.assets.teeth)
        self.detail_profile=os.getenv('FEATHERTALK_DETAIL_PROFILE',self.assets.settings['detail_profile']).strip().lower()
        if self.detail_profile not in ('original','model_idle'):raise ValueError('Unknown production detail profile')
        self.detail_filter=self.idle_appearance=None;self.detail_last_ms=0.
        if self.detail_profile=='model_idle':
            from detail_balance import DetailBalance,IdleAppearance
            self.detail_filter=DetailBalance(self);self.idle_appearance=IdleAppearance(self)
        self.idle_video_path=root/'idle.mp4' if self.idle_appearance is None else self.idle_appearance.video_path
        self.idle_poster_path=root/'poster.jpg' if self.idle_appearance is None else self.idle_appearance.poster_path

    def idle_frame(self,index):
        return self.frames[index].copy() if self.idle_appearance is None else self.idle_appearance.frame(index)

    def begin(self,frame):
        self.cursor=int(frame)%self.count;self.indices=[]
        self.teeth_rows=[]
        if self.teeth is not None:self.teeth.reset()

    @torch.inference_mode()
    def render(self,window):
        idx=self.cursor;self.cursor=(idx+1)%self.count;self.indices.append(idx)
        image_input=self.model_inputs[idx:idx+1]
        pred=self.visual(image_input,reshape_audio_feat(torch.from_numpy(window))[None].to(self.device))[0]
        prediction=(pred.cpu().numpy().transpose(1,2,0)*255).clip(0,255).astype(np.uint8)
        image=self.frames[idx].copy();original=self.crops[idx].copy();generated=original.copy()
        generated[4:148,4:148]=prediction
        alpha=self.alpha if self.frame_alphas is None else self.frame_alphas[idx]
        mixed=np.rint(generated.astype(np.float32)*alpha+original.astype(np.float32)*(1-alpha)).clip(0,255).astype(np.uint8)
        x1,y1,x2,y2=self.bboxes[idx]
        changed=cv2.resize(mixed,(x2-x1,y2-y1),interpolation=cv2.INTER_LINEAR)
        if self.frame_alphas is None:
            image[y1:y2,x1:x2]=changed
        else:
            selected=cv2.resize(alpha[:,:,0],(x2-x1,y2-y1))>0
            image[y1:y2,x1:x2][selected]=changed[selected]
        if self.teeth_mode=='new' and self.teeth is not None:
            image=self.teeth.process(image,idx);self.teeth_rows.append(self.teeth.last)
        else:self.teeth_rows.append({'ms':0.,'replaced':False})
        self.detail_last_ms=0.
        if self.detail_filter is not None:
            image,self.detail_last_ms=self.detail_filter.process(image,idx)
        return image,prediction

class LoopSession(Session):
    def __init__(self,engine,mode='fast',start_frame=0,teeth='model'):
        if teeth not in ('model','new'):raise ValueError('Unknown teeth mode')
        if teeth=='new' and engine.teeth is None:raise ValueError('New teeth assets are unavailable')
        engine.teeth_mode=teeth
        engine.begin(start_frame)
        super().__init__(engine,mode)
        self.start_frame=int(start_frame)%engine.count
        self.teeth_mode=teeth

    def push(self,samples,final=False):
        return list(self.iter_push(samples,final))

    def iter_push(self,samples,final=False):
        self.pcm=np.concatenate([self.pcm,np.asarray(samples,dtype=np.float32)])
        received=len(self.pcm)/16000;begin=time.perf_counter()
        total=max(0,(len(self.pcm)-80)//640)
        if final:
            total=len(self.pcm)//640
            self.pcm=np.pad(self.pcm,(0,max(0,total*640+80-len(self.pcm))))
        eligible=total if final else max(0,total-self.lookahead)
        if eligible<=self.next_frame:return
        left=max(0,self.next_frame-self.history)
        features=self.engine.encode(self.pcm[left*640:]);encoded=time.perf_counter();count=0
        for idx in range(self.next_frame,eligible):
            local=idx-left;window=gather_audio_window(features,local).numpy()
            image,pred=self.engine.render(window);self.engine.sync()
            self.rows.append({'frame':idx,'pts_seconds':idx/25,'received_seconds':received,
                'buffer_ms':(received-idx/25)*1000,'compute_since_push_ms':(time.perf_counter()-begin)*1000,
                'eof_flush':final,'base_frame':self.engine.indices[idx],
                'teeth_ms':self.engine.teeth_rows[idx]['ms'],'teeth_replaced':self.engine.teeth_rows[idx]['replaced']})
            self.rows[-1]['detail_ms']=self.engine.detail_last_ms
            self.feature_parts.append(features[local].copy());self.next_frame=idx+1;count+=1
            # Publish each frame as soon as it is generated, so other frames
            # in the same PCM packet cannot delay the first frame's transport.
            yield idx,image,pred
        self.blocks.append({'frames':count,'encode_ms':(encoded-begin)*1000,
            'total_ms':(time.perf_counter()-begin)*1000,'received_seconds':received,'eof_flush':final})
