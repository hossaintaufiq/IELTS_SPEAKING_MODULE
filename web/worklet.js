// Mic capture: downsample the browser's native rate to 16 kHz mono and post 40 ms Int16 chunks.
class MicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;   // `sampleRate` is the AudioContext's rate (44.1k / 48k)
    this.pos = 0;
    this.buf = [];
  }
  process(inputs) {
    const ch = inputs[0][0];
    if (!ch) return true;
    // Average-and-decimate: crude but adequate for speech; avoids a heavy resampler.
    for (let i = 0; i < ch.length; i++) {
      this.pos += 1;
      this.acc = (this.acc || 0) + ch[i];
      if (this.pos >= this.ratio) {
        this.buf.push(this.acc / this.pos);
        this.acc = 0; this.pos -= this.ratio;
      }
    }
    while (this.buf.length >= 640) {   // 640 samples = 40 ms at 16 kHz
      const out = new Int16Array(640);
      for (let i = 0; i < 640; i++) {
        const s = Math.max(-1, Math.min(1, this.buf[i]));
        out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      this.buf.splice(0, 640);
      this.port.postMessage(out.buffer, [out.buffer]);
    }
    return true;
  }
}
registerProcessor("mic-processor", MicProcessor);
