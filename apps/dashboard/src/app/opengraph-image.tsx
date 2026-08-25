import { ImageResponse } from 'next/og';

export const alt = 'WebChat AI - AI Chatbot for Your Website';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

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
        <div
          style={{
            width: 96,
            height: 96,
            borderRadius: 24,
            backgroundColor: '#2563eb',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <svg
            width="56"
            height="56"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#ffffff"
            strokeWidth="2"
          >
            <path d="M12 8V4H8" />
            <rect width="16" height="12" x="4" y="8" rx="2" />
            <path d="M2 14h2M20 14h2M15 13v2M9 13v2" />
          </svg>
        </div>
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
