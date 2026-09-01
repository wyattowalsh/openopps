const PNG_SIG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

export function pngSize(bytes) {
  const buf = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes);
  if (buf.length < 24 || !PNG_SIG.equals(buf.subarray(0, 8))) {
    throw new Error("not a PNG");
  }
  const chunk = buf.toString("ascii", 12, 16);
  if (chunk !== "IHDR") {
    throw new Error("PNG missing IHDR");
  }
  return {
    width: buf.readUInt32BE(16),
    height: buf.readUInt32BE(20),
  };
}

export function assertPngSize(bytes, width, height, label) {
  const size = pngSize(bytes);
  if (size.width !== width || size.height !== height) {
    throw new Error(
      `${label}: expected ${width}x${height}, got ${size.width}x${size.height}`,
    );
  }
  return size;
}
