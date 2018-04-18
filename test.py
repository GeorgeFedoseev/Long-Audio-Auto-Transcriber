# =* coding: utf-8 *=
import os
import sys
import subprocess

import webrtcvad
import wave
import shutil


def check_dependencies_installed():
    try:
        subprocess.check_output(['soxi'], stderr=subprocess.STDOUT)        
        subprocess.check_output(['ffmpeg', '--help'], stderr=subprocess.STDOUT)
    except Exception as ex:
        print 'ERROR: some of dependencies are not installed: ffmpeg or sox: '+str(ex)
        return False

    return True


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


SPEECH_FRAME_SEC = 0.01

def slice_audio_by_silence(wave_obj, min_audio_length=5, max_audio_length=20):
    vad = webrtcvad.Vad(1)

    samples_per_second = wave_obj.getframerate()    
    samples_per_frame = int(SPEECH_FRAME_SEC*samples_per_second)
    total_samples = wave_obj.getnframes()    
    
    wave_obj.setpos(0)

    out_pieces = []

    current_piece_length_sec = 0
    current_piece_samples = ""

    total_length = 0

    
    while wave_obj.tell() < total_samples:       
        
        wav_samples = wave_obj.readframes(samples_per_frame)
        current_frame_length_sec = float(samples_per_frame)/samples_per_second       

        
        try:
            is_speech = vad.is_speech(wav_samples, samples_per_second)
        except Exception as ex:
            print("VAD Exception: %s" % str(ex))
            continue

        current_piece_length_sec += current_frame_length_sec
        current_piece_samples += wav_samples

        if (current_piece_length_sec > min_audio_length):
            if not is_speech:
                # push current piece to out
                out_pieces.append(current_piece_samples)
                total_length += current_piece_length_sec
                # and reset current piece
                current_piece_samples = ""
                current_piece_length_sec = 0
            else:
                if current_piece_length_sec > max_audio_length:
                    print("WARNING: forced cut not at silence but at max_audio_length = %f sec" % max_audio_length)
                    # push current piece to out
                    out_pieces.append(current_piece_samples)
                    total_length += current_piece_length_sec
                    # and reset current piece
                    current_piece_samples = ""
                    current_piece_length_sec = 0   



    # add last piece
    #print("Last piece length is %f" % current_piece_length_sec)
    # push current piece to out
    #out_pieces.append(current_piece_samples)    

    return out_pieces, total_length/len(out_pieces)

def save_wave_samples_to_file(wave_samples, n_channels, byte_width, sample_rate, file_path):
    out = wave.open(file_path, "w")
    length = len(wave_samples)
    out.setparams((n_channels, byte_width, sample_rate, length, 'NONE', 'not compressed'))    
    out.writeframes(wave_samples)
    out.close()

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




def test():
    if not check_dependencies_installed():
        return

    curr_dir_path = os.getcwd()

    test_audio_file_path = os.path.join(curr_dir_path, "data/test3.mp3")



    wav_vol_corr_path = os.path.join(curr_dir_path, "data/test_vol_corr.wav")
    if not os.path.exists(wav_vol_corr_path):
        print("correct_volume")
        correct_volume(test_audio_file_path, wav_vol_corr_path)

    wav_filtered_path = os.path.join(curr_dir_path, "data/test_filtered.wav")
    if not os.path.exists(wav_filtered_path):    
        print("apply_bandpass_filter")
        apply_bandpass_filter(wav_vol_corr_path, wav_filtered_path)

    wave_o = wave.open(wav_filtered_path, "r")

    print("slice audio")
    pieces, avg_len_sec = slice_audio_by_silence(wave_o)

    print("total pieces: %i, avg_len_sec: %f" % (len(pieces), avg_len_sec))

    # write all piecese to folder

    # first remove prev pieces
    pieces_folder_path = os.path.join(curr_dir_path, "data/pieces")


    if os.path.exists(pieces_folder_path):
        shutil.rmtree(pieces_folder_path)

    os.makedirs(pieces_folder_path)


    transcript_lines = []
    for i, piece in enumerate(pieces):
        piece_path = os.path.join(pieces_folder_path, "piece_%i.wav" % i)
        save_wave_samples_to_file(piece, n_channels=1, byte_width=2, sample_rate=16000, file_path=piece_path)

        # run inference
        text = run_deepspeech_for_wav(piece_path)
        print(text)
        transcript_lines.append(text)

    # write whole transcript
    transcript_path = os.path.join(curr_dir_path, "data/transcript.txt")
    f = open(transcript_path, "w")
    f.write("\n".join(transcript_lines))
    f.close()

if __name__ == "__main__":
    test()













