import { readFileSync } from 'node:fs';
import path from 'node:path';
import { ImageResponse } from 'next/og';

export const alt = 'WebChat AI - AI Chatbot for Your Website';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

const logoDataUri = `data:image/png;base64,${readFileSync(
  path.join(process.cwd(), 'public/logo.png'),
).toString('base64')}`;

export default function OpengraphImage() {
  return new ImageResponse(
    <div
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: '#ffffff',
        position: 'relative',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 14,
          backgroundImage: 'linear-gradient(90deg, #2563eb, #f59e0b)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: -180,
          right: -120,
          width: 560,
          height: 560,
          borderRadius: 9999,
          backgroundColor: 'rgba(37, 99, 235, 0.08)',
        }}
      />
      <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
        <img src={logoDataUri} width={96} height={96} alt="" style={{ objectFit: 'contain' }} />
        <div style={{ fontSize: 64, fontWeight: 700, color: '#0a0a0a' }}>WebChat AI</div>
      </div>
      <div style={{ marginTop: 32, fontSize: 40, color: '#52525b' }}>
        AI Chatbot for Your Website
      </div>
      <div
        style={{
          marginTop: 28,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          fontSize: 26,
          color: '#71717a',
        }}
      >
        <span
          style={{
            width: 12,
            height: 12,
            borderRadius: 9999,
            backgroundColor: '#f59e0b',
            display: 'flex',
          }}
        />
        Trained on your website content
      </div>
    </div>,
    { ...size },
  );
}
