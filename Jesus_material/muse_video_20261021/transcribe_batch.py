"""Offline cached Whisper-tiny wording check; no external API or model download."""
import json,re,hashlib
from pathlib import Path
import torch,soundfile as sf
from transformers import WhisperProcessor,WhisperForConditionalGeneration
torch.set_num_threads(2)
root=Path('/batch');out=root/'review';plan=json.loads((root/'generation_plan.json').read_text())
pending=[];results=[]
for item in plan['items']:
    if item['kind']!='speech':continue
    wav=out/(item['id']+'.wav');dest=out/(item['id']+'_transcript.json')
    if not wav.exists():continue
    sha=hashlib.sha256(wav.read_bytes()).hexdigest()
    if dest.exists()and json.loads(dest.read_text()).get('wav_sha256')==sha:results.append(json.loads(dest.read_text()));continue
    pending.append((item,wav,dest,sha))
if pending:
    processor=WhisperProcessor.from_pretrained('/whisper',local_files_only=True)
    model=WhisperForConditionalGeneration.from_pretrained('/whisper',local_files_only=True).eval()
    def words(s):return re.findall(r"[a-z]+(?:'[a-z]+)?",s.lower())
    def wer(a,b):
        previous=list(range(len(b)+1))
        for i,x in enumerate(a,1):
            current=[i]
            for j,y in enumerate(b,1):current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(x!=y)))
            previous=current
        return previous[-1]/max(1,len(a))
    for item,wav,dest,sha in pending:
        samples,sr=sf.read(wav,dtype='float32');assert sr==16000
        inputs=processor(samples,sampling_rate=sr,return_tensors='pt',return_attention_mask=True)
        with torch.inference_mode():tokens=model.generate(inputs.input_features,attention_mask=inputs.attention_mask,forced_decoder_ids=processor.get_decoder_prompt_ids(language='en',task='transcribe'),max_new_tokens=128)
        transcript=processor.batch_decode(tokens,skip_special_tokens=True)[0]
        error=wer(words(item['dialogue']),words(transcript))
        row={'id':item['id'],'expected_dialogue':item['dialogue'],'transcript':transcript,'word_error_rate':error,'requires_manual_wording_review':error>.25,'wav_sha256':sha,'method':'local cached Whisper-tiny, English transcription; ASR error is possible; not a lip-sync or voice-identity verification'}
        dest.write_text(json.dumps(row,indent=2));results.append(row);print(json.dumps(row),flush=True)
(out/'transcripts.json').write_text(json.dumps(results,indent=2))
