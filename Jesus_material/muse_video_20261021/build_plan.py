"""Build the Muse generation plan and per-clip prompts for the Jesus base (v2).

v2 (2026-10-21, after the pilot and prompt test):
- template = experiment B_still_photo: head locked, only lips/jaw/blinks move
  (pilot clips turned the head up to ~50 deg; B measured ~5 deg yaw);
- every line lengthened to ~27-30 words so speech fills ~0.3-9.3 s; with the
  original ~22-word lines Muse repeated the last clause to fill 10 s.
Phonetic focus and train/validation split follow the earlier 24-line set.
Re-running overwrites plan/prompts only, never native videos or results.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / 'reference.png'
VERSION = 2

# id: (split, focus, line)
LINES = {
    'speech_01': ('train', '/p b m/ lip closure and release',
                  'Please bring my blue bag before we leave. Maybe we can buy some bread, make a simple meal, and meet Ben by the park before the bus comes back.'),
    'speech_02': ('train', '/f v/ upper teeth on lower lip',
                  'Five friends visited the village on Friday. We found fresh flowers, shared a favorite meal, and enjoyed a very peaceful evening together before driving home through the soft fog.'),
    'speech_03': ('train', '/th/ tongue between teeth',
                  'I think these three things belong together. Put them over there, beside the other books, and then we can talk through the whole plan, one step at a time.'),
    'speech_04': ('train', '/s z/ continuous sibilants',
                  'Sarah says the streets are busy this morning. We can visit the stores, choose some supplies, and discuss our plans as we walk slowly past the square at noon.'),
    'speech_05': ('train', '/sh zh ch j/',
                  'Shall we choose a jacket for James? We can measure the shelves, check the usual sizes, and share our decision before lunch today, then change it if he wishes.'),
    'speech_06': ('train', '/i I e/ front vowels',
                  'Please sit here and tell me what you see. The green seats look different in this light, but the red desk is clear, and the window seems a little brighter.'),
    'speech_07': ('train', '/ae a ^/ open vowels',
                  'My father left a black bag beside the cup. After lunch, we can walk past the shop and ask about the map together, and then catch the last tram.'),
    'speech_08': ('train', '/u U o/ rounded vowels',
                  'You could choose the blue room with a good view. We can go home soon, cook some food, and enjoy a quiet evening, then look at the moon.'),
    'speech_09': ('train', '/ai au oi/ diphthongs',
                  'Now is a good time to try another choice. I found a quiet house outside town, and I would like to show you the garden and the old oak tree.'),
    'speech_10': ('train', '/w r l/ glides and liquids',
                  'We will walk along the river and look for the red building. When we arrive, Laura can tell us where the little room is, and we will rest a while.'),
    'speech_11': ('train', 'mixed conversational English',
                  'Thank you for joining me today. Tell me about your plans, and we can work through the details together, one step at a time, until everything feels clear.'),
    'speech_12': ('validation', 'question and statement with two short pauses',
                  'Are you ready to begin? Take a moment. Then tell me what happened this morning, and we can decide what to do next together, without any hurry at all.'),
    'speech_25': ('train', 'balanced English, bilabials',
                  'Pack the paper box beside my backpack. Before Monday, bring the blue mug home and remind me to buy more milk, maybe some plums, and a bit of butter.'),
    'speech_26': ('train', 'balanced English, labiodentals',
                  'The ferry leaves after five, so we have enough time. Find your gloves, fill the flask, and follow me down the path to the far end of the pier.'),
    'speech_27': ('train', 'balanced English',
                  'Please leave the envelope by the front window. Move the heavy basket carefully, and give me a moment to finish my breakfast before we leave for the market.'),
    'speech_28': ('train', 'balanced English, th',
                  'Those thin curtains let the sunlight through. I think the room feels brighter now, and there is space for another small table, maybe with three chairs by the wall.'),
    'speech_29': ('train', 'balanced English, sibilants',
                  'These oranges smell fresh, and the lemons look nice. Choose six pieces for the guests, then place the rest beside the sink and rinse the glass bowls for later.'),
    'speech_30': ('train', 'balanced English, sh/ch/j',
                  'The chef usually measures each portion before serving lunch. Choose a dish you enjoy, and share your suggestion with the manager tomorrow at the usual meeting.'),
    'speech_31': ('train', 'balanced English, front vowels and l',
                  'The little bell rings when the green light appears. Keep the lid beside the shelf, and let me see which piece fits, then we will lock the lid.'),
    'speech_32': ('train', 'balanced English, open vowels',
                  'Sam left his hat on the counter after lunch. Our mother asked us to pack the cups and carry the basket upstairs, and then sweep the back porch.'),
    'speech_33': ('train', 'balanced English, rounded vowels',
                  'The soup should cool before you taste it. Put your spoon on the wooden tray, and let the cook know how it tastes, whether it needs more salt or pepper.'),
    'speech_34': ('train', 'balanced English, diphthongs',
                  'Enjoy the bright afternoon while the clouds are passing. I might ride my bike around the square and buy a small gift tonight for my oldest friend.'),
    'speech_35': ('train', 'balanced English, r and l',
                  'We walked around the lake before the rain began. Riley remembered the narrow road, and led us toward a warm little bakery nearby, where we waited out the storm.'),
    'speech_36': ('validation', 'question, short answer, statement',
                  'Would you prefer coffee or tea? Either is fine. Let me know your choice, and we can enjoy a few quiet minutes together before the others arrive.'),
}

HEAD = (
    'Generate a video from the attached photo, using it as the exact first frame. Vertical 2:3 portrait, 10 seconds, '
    '{audio} No captions or on-screen text. Photorealistic real-camera footage of this exact man, same face, hair, '
    'beard, clothes, shoreline background and knee-length framing as the photo. Everything stays exactly as still as '
    'the photo except {moving}: his head is locked in place as if braced on a headrest, eyes fixed on the lens, face '
    'perfectly frontal, no head turn, tilt, nod or sway, no gestures, body motionless. {only} The camera never moves.'
)

SPEECH = HEAD.format(
    audio='with native synchronized speech audio.',
    moving='his mouth',
    only='Only his lips, jaw and occasional natural blinks move.',
) + (
    ' He says exactly once, in a calm, even adult male General American English voice: "{line}" He starts speaking '
    'immediately and speaks at a steady unhurried pace that fills the whole clip; the lip movement is tightly '
    'synchronized with the audio, and he closes his lips softly after the last word. No other words, no repetition, '
    'no music, no sound effects. Keep the head absolutely still throughout.'
)

IDLE = {
    'idle_waiting': HEAD.format(
        audio='silent apart from faint natural shore ambience.',
        moving='his eyes and breathing',
        only=('He is silently waiting for the viewer to speak: lips softly closed, jaw relaxed, a calm neutral '
              'expression. Only natural blinks every few seconds and very subtle breathing in the chest move.'),
    ) + ' No speaking, no mouth movement, no smile, no music. Keep the head absolutely still throughout.',
    'idle_listening': HEAD.format(
        audio='silent apart from faint natural shore ambience.',
        moving='his eyes and breathing',
        only=('He is quietly listening to the viewer with attentive, gentle eyes: lips softly closed and touching, '
              'jaw relaxed. Only natural blinks, tiny eye refocusing and very subtle breathing in the chest move.'),
    ) + ' No speaking, no mouth movement, no smile, no music. Keep the head absolutely still throughout.',
}


def main():
    ref_sha = hashlib.sha256(REFERENCE.read_bytes()).hexdigest()
    items = []
    for item_id, (split, focus, line) in LINES.items():
        items.append(('speech', item_id, split, focus, line, SPEECH.format(line=line)))
    for item_id, prompt in IDLE.items():
        items.append(('idle', item_id, None, None, None, prompt))
    plan_items = []
    for kind, item_id, split, focus, line, prompt in items:
        prompt_file = ROOT / 'prompts' / f'{item_id}.txt'
        prompt_file.write_text(prompt + '\n', encoding='utf-8')
        plan_items.append({
            'id': item_id, 'kind': kind, 'split': split, 'focus': focus, 'dialogue': line,
            'words': len(line.split()) if line else None,
            'prompt_file': f'prompts/{item_id}.txt',
            'output_file': f'native/{item_id}.mp4',
            'status': 'planned',
        })
    plan = {
        'version': VERSION,
        'character': 'Jesus (photoreal)',
        'service': 'Muse web chat (muse.ai), driven through Chrome',
        'reference': 'reference.png',
        'reference_source': '../JESUS_SEA_BASE.png',
        'reference_sha256': ref_sha,
        'reference_lower_face_width_at_720': 108.6,
        'muse_output_observed': '768x1152 h264 24fps 240 frames 10.0s, AAC mono 24 kHz, no visible watermark',
        'template_source': 'prompts/experiments/B_still_photo.txt',
        'acceptance': {
            'head_motion': 'head_motion.py LIMITS (smoothed p5-p95 spread)',
            'wording': 'line spoken once, no repeated clause (Whisper full + last 3 s)',
            'visual': 'identity matches reference, no watermark/text, full framing kept',
        },
        'rules': [
            'one new Muse chat per clip, reference.png uploaded fresh each time',
            'never use a previous clip or frame as input',
            'save the downloaded file unchanged, record SHA256 and the exact prompt sent',
            'a failed clip is regenerated with the same prompt; the failed file is kept under native/rejected/',
        ],
        'superseded': 'v1 pilot clips (head turns, repeated clause) moved to native/v1_pilot/',
        'items': plan_items,
    }
    (ROOT / 'generation_plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    print(len(plan_items), 'items; words', [i['words'] for i in plan_items if i['words']])


if __name__ == '__main__':
    main()
