/**
 * Audio streaming and playback subsystem for Yulya Studio V2.
 * Captures browser microphone at 16kHz mono 16-bit PCM for Gemini Live,
 * and streams 24kHz PCM from the assistant for real-time speech playback.
 */

export class AudioStreamer {
  private micStream: MediaStream | null = null;
  private audioCtx: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  private isMuted: boolean = false;
  private onPcmChunk: ((base64Pcm: string) => void) | null = null;

  // Playback context
  private playbackCtx: AudioContext | null = null;
  private nextPlayTime: number = 0;

  constructor(onChunk: (base64Pcm: string) => void) {
    this.onPcmChunk = onChunk;
  }

  public setMuted(muted: boolean) {
    this.isMuted = muted;
  }

  public async startMicrophone(): Promise<boolean> {
    try {
      this.micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      this.audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)({
        sampleRate: 16000,
      });

      const source = this.audioCtx.createMediaStreamSource(this.micStream);
      // Buffer size 4096 gives ~256ms chunk intervals at 16kHz
      this.processor = this.audioCtx.createScriptProcessor(4096, 1, 1);

      this.processor.onaudioprocess = (e) => {
        if (this.isMuted || !this.onPcmChunk) return;

        const inputData = e.inputBuffer.getChannelData(0);
        // Convert Float32Array [-1.0, 1.0] to Int16Array
        const pcm16 = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }

        // Convert Int16 buffer to Base64
        const bytes = new Uint8Array(pcm16.buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) {
          binary += String.fromCharCode(bytes[i]);
        }
        const b64 = btoa(binary);
        this.onPcmChunk(b64);
      };

      source.connect(this.processor);
      this.processor.connect(this.audioCtx.destination);
      return true;
    } catch (err) {
      console.warn('[AUDIO] Failed to access microphone:', err);
      return false;
    }
  }

  public stopMicrophone() {
    if (this.processor) {
      this.processor.disconnect();
      this.processor = null;
    }
    if (this.audioCtx) {
      this.audioCtx.close().catch(() => {});
      this.audioCtx = null;
    }
    if (this.micStream) {
      this.micStream.getTracks().forEach((t) => t.stop());
      this.micStream = null;
    }
  }

  public playPcmChunk(base64Pcm: string, sampleRate = 24000) {
    try {
      if (!this.playbackCtx) {
        this.playbackCtx = new (window.AudioContext || (window as any).webkitAudioContext)({
          sampleRate,
        });
        this.nextPlayTime = this.playbackCtx.currentTime;
      }

      if (this.playbackCtx.state === 'suspended') {
        this.playbackCtx.resume();
      }

      const binary = atob(base64Pcm);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
      }
      const int16 = new Int16Array(bytes.buffer);

      const buffer = this.playbackCtx.createBuffer(1, int16.length, sampleRate);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < int16.length; i++) {
        channel[i] = int16[i] / 32768.0;
      }

      const source = this.playbackCtx.createBufferSource();
      source.buffer = buffer;
      source.connect(this.playbackCtx.destination);

      const now = this.playbackCtx.currentTime;
      if (this.nextPlayTime < now) {
        this.nextPlayTime = now;
      }
      source.start(this.nextPlayTime);
      this.nextPlayTime += buffer.duration;
    } catch (err) {
      console.warn('[AUDIO PLAYBACK ERROR]', err);
    }
  }

  public resetPlayback() {
    if (this.playbackCtx) {
      this.nextPlayTime = this.playbackCtx.currentTime;
    }
  }
}
