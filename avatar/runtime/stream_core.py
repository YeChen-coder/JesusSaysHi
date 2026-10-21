"""Bounded-history streaming adapter; only received PCM is visible to the encoder.

This approximation preserves released weights. Symmetric TCN and time-wide
GroupNorm mean bounded windows cannot reproduce full-utterance features exactly.
"""
import time
from pathlib import Path
import cv2,numpy as np,torch
from data_utils.feather_hubert.feather_hubert import load_feather_hubert,get_feather_hubert_from_16k_speech
from inference import load_model,prepare_model_input,paste_prediction
from face_utils import reshape_audio_feat,gather_audio_window

MODES={'fast':{'lookahead':0,'chunk_ms':40},'balanced':{'lookahead':10,'chunk_ms':80},'quality':{'lookahead':25,'chunk_ms':160}}

class Engine:
    def __init__(self,checkpoint='/work/checkpoints/last.pth',device='cuda',base_image='/work/data/base.jpg',base_landmarks='/work/data/base.lms'):
        torch.set_num_threads(4); self.device=torch.device(device)
        if device=='cuda':torch.cuda.set_per_process_memory_fraction(.45)
        begin=time.perf_counter()
        self.audio=load_feather_hubert('/work/feather_hubert.pth',self.device)
        self.visual=load_model(checkpoint,self.device)
        self.image=cv2.imread(str(base_image))
        self.image_input,self.crop,self.bbox,self.original_size=prepare_model_input(self.image,str(base_landmarks),self.device)
        # Warm up separately from session timing.
        with torch.inference_mode():
            self.visual(self.image_input,torch.zeros(1,40,1024,device=self.device))
            get_feather_hubert_from_16k_speech(np.zeros(16000,dtype=np.float32),self.audio,self.device)
        self.sync();self.load_seconds=time.perf_counter()-begin
    def sync(self):
        if self.device.type=='cuda':torch.cuda.synchronize()
    @torch.inference_mode()
    def encode(self,samples):
        hidden=get_feather_hubert_from_16k_speech(samples,self.audio,self.device)
        return hidden[:(len(hidden)//2)*2].numpy().reshape(-1,2,1024)
    @torch.inference_mode()
    def render(self,window):
        p=self.visual(self.image_input,reshape_audio_feat(torch.from_numpy(window)).unsqueeze(0).to(self.device))[0]
        prediction=(p.cpu().numpy().transpose(1,2,0)*255).clip(0,255).astype(np.uint8)
        image=self.image.copy();paste_prediction(image,prediction,self.crop.copy(),self.bbox,self.original_size)
        # Keep the native still for compositing, then publish a 768x1152 frame.
        # The visual model itself always operates at the released 144x144 size.
        return cv2.resize(image,(768,1152),interpolation=cv2.INTER_AREA),prediction

class Session:
    def __init__(self,engine,mode='balanced',history_seconds=4):
        self.engine=engine;self.mode=mode;self.lookahead=MODES[mode]['lookahead'];self.history=int(history_seconds*25)
        self.pcm=np.empty(0,dtype=np.float32);self.next_frame=0;self.blocks=[];self.rows=[];self.feature_parts=[]
    def push(self,samples,final=False):
        self.pcm=np.concatenate([self.pcm,np.asarray(samples,dtype=np.float32)])
        received=len(self.pcm)/16000;begin=time.perf_counter()
        total=max(0,(len(self.pcm)-80)//640)
        # Only pad at EOF. Steady state never invents samples which have not arrived.
        if final:
            total=len(self.pcm)//640
            pad=max(0,total*640+80-len(self.pcm));self.pcm=np.pad(self.pcm,(0,pad))
        eligible=total if final else max(0,total-self.lookahead)
        if eligible<=self.next_frame:return []
        left=max(0,self.next_frame-self.history)
        features=self.engine.encode(self.pcm[left*640:])
        frames=[];encoder_end=time.perf_counter()
        for idx in range(self.next_frame,eligible):
            local=idx-left
            window=gather_audio_window(features,local).numpy()
            image,pred=self.engine.render(window);self.engine.sync()
            self.rows.append({'frame':idx,'pts_seconds':idx/25,'received_seconds':received,'buffer_ms':(received-idx/25)*1000,'compute_since_push_ms':(time.perf_counter()-begin)*1000,'eof_flush':final})
            self.feature_parts.append(features[local].copy());frames.append((idx,image,pred))
        self.next_frame=eligible;self.blocks.append({'frames':len(frames),'encode_ms':(encoder_end-begin)*1000,'total_ms':(time.perf_counter()-begin)*1000,'received_seconds':received,'eof_flush':final})
        return frames
