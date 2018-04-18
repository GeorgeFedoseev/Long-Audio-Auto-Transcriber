'''
Requirements:
+ pyaudio - `pip install pyaudio`
+ py-webrtcvad - `pip install webrtcvad`
'''
import webrtcvad
import collections
import sys
import signal
import pyaudio

import os
import subprocess

from array import array
from struct import pack
import wave
import time

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK_DURATION_MS = 30       # supports 10, 20 and 30 (ms)
PADDING_DURATION_MS = 1500   # 1 sec jugement
CHUNK_SIZE = int(RATE * CHUNK_DURATION_MS / 1000)  # chunk to read
CHUNK_BYTES = CHUNK_SIZE * 2  # 16bit = 2 bytes, PCM
NUM_PADDING_CHUNKS = int(PADDING_DURATION_MS / CHUNK_DURATION_MS)
# NUM_WINDOW_CHUNKS = int(240 / CHUNK_DURATION_MS)
NUM_WINDOW_CHUNKS = int(400 / CHUNK_DURATION_MS)  # 400 ms/ 30ms  ge
NUM_WINDOW_CHUNKS_END = NUM_WINDOW_CHUNKS * 2

START_OFFSET = int(NUM_WINDOW_CHUNKS * CHUNK_DURATION_MS * 0.5 * RATE)

vad = webrtcvad.Vad(1)

pa = pyaudio.PyAudio()
stream = pa.open(format=FORMAT,
                 channels=CHANNELS,
                 rate=RATE,
                 input=True,
                 start=False,
                 # input_device_index=2,
                 frames_per_buffer=CHUNK_SIZE)


got_a_sentence = False
leave = False


def handle_int(sig, chunk):
    global leave, got_a_sentence
    leave = True
    got_a_sentence = True


def record_to_file(path, data, sample_width):
    "Records from the microphone and outputs the resulting data to 'path'"
    # sample_width, data = record()
    data = pack('<' + ('h' * len(data)), *data)
    wf = wave.open(path, 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(sample_width)
    wf.setframerate(RATE)
    wf.writeframes(data)
    wf.close()


def normalize(snd_data):
    "Average the volume out"
    MAXIMUM = 32767  # 16384
    times = float(MAXIMUM) / max(abs(i) for i in snd_data)
    r = array('h')
    for i in snd_data:
        r.append(int(i * times))
    return r

def apply_bandpass_filter(in_path, out_path):
    # ffmpeg -i input.wav -acodec pcm_s16le -ac 1 -ar 16000 -af lowpass=3000,highpass=200 output.wav
    p = subprocess.Popen(["ffmpeg", "-y",
        #"-acodec", "pcm_s16le",
         "-i", in_path,    
         "-acodec", "pcm_s16le",
         "-ac", "1",
         "-af", "lowpass=3000,highpass=200",
         "-ar", "16000",         
         out_path
         ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out, err = p.communicate()

    if p.returncode != 0:
        raise Exception("Failed to apply bandpass filter: %s" % str(err))

def correct_volume(in_path, out_path, db=-10):
    # sox input.wav output.wav gain -n -10
    p = subprocess.Popen(["sox",
         in_path,             
         out_path,
         "gain",
         "-n", str(db)
         ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out, err = p.communicate()

    if p.returncode != 0:
        raise Exception("Failed to correct volume: %s" % str(err))

def run_deepspeech_for_wav(wav_file_path):
    curr_dir_path = os.getcwd()
    graph_path = os.path.join(curr_dir_path, "data/deepspeech_data/output_graph.pb")
    alphabet_path = os.path.join(curr_dir_path, "data/deepspeech_data/alphabet.txt")

    p = subprocess.Popen(["deepspeech",        
         graph_path,
         alphabet_path,
         wav_file_path,         
         ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out, err = p.communicate()

    #print out

    if p.returncode != 0:
        raise Exception("Failed to apply bandpass filter: %s" % str(err))

    return out

signal.signal(signal.SIGINT, handle_int)

while not leave:
    ring_buffer = collections.deque(maxlen=NUM_PADDING_CHUNKS)
    triggered = False
    voiced_frames = []
    ring_buffer_flags = [0] * NUM_WINDOW_CHUNKS
    ring_buffer_index = 0

    ring_buffer_flags_end = [0] * NUM_WINDOW_CHUNKS_END
    ring_buffer_index_end = 0
    buffer_in = ''
    # WangS
    raw_data = array('h')
    index = 0
    start_point = 0
    StartTime = time.time()
    print("* recording: ")
    stream.start_stream()

    while not got_a_sentence and not leave:
        chunk = stream.read(CHUNK_SIZE)
        # add WangS
        raw_data.extend(array('h', chunk))
        index += CHUNK_SIZE
        TimeUse = time.time() - StartTime

        active = vad.is_speech(chunk, RATE)

        sys.stdout.write('1' if active else '_')
        ring_buffer_flags[ring_buffer_index] = 1 if active else 0
        ring_buffer_index += 1
        ring_buffer_index %= NUM_WINDOW_CHUNKS

        ring_buffer_flags_end[ring_buffer_index_end] = 1 if active else 0
        ring_buffer_index_end += 1
        ring_buffer_index_end %= NUM_WINDOW_CHUNKS_END

        # start point detection
        if not triggered:
            ring_buffer.append(chunk)
            num_voiced = sum(ring_buffer_flags)
            if num_voiced > 0.8 * NUM_WINDOW_CHUNKS:
                sys.stdout.write(' Open ')
                triggered = True
                start_point = index - CHUNK_SIZE * 20  # start point
                # voiced_frames.extend(ring_buffer)
                ring_buffer.clear()
        # end point detection
        else:
            # voiced_frames.append(chunk)
            ring_buffer.append(chunk)
            num_unvoiced = NUM_WINDOW_CHUNKS_END - sum(ring_buffer_flags_end)
            if num_unvoiced > 0.90 * NUM_WINDOW_CHUNKS_END or TimeUse > 10:
                sys.stdout.write(' Close ')
                triggered = False
                got_a_sentence = True

        sys.stdout.flush()

    sys.stdout.write('\n')
    # data = b''.join(voiced_frames)

    stream.stop_stream()
    print("* done recording")
    got_a_sentence = False

    # write to file
    raw_data.reverse()
    for index in range(start_point):
        raw_data.pop()
    raw_data.reverse()
    raw_data = normalize(raw_data)

    path = "recording.wav"
    record_to_file(path, raw_data, 2)

    #correct_volume_path = path+"_vol_corr.wav"
    #correct_volume(path, correct_volume_path)

    filtered_path = path+"_filtered.wav"
    apply_bandpass_filter(path, filtered_path)


    print "\n-------------"
    print run_deepspeech_for_wav(filtered_path)
    print "-------------"

    #leave = True

stream.close()