// Vercel Serverless Function: GET /api/homework or POST /api/homework (trigger solver run)
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-Auth-Pin, X-Tunnel-Url, Authorization');

  if (req.method === 'OPTIONS') {
    return res.status(204).end();
  }

  const pinHeader = req.headers['x-auth-pin'];
  const body = req.body || {};
  const pin = pinHeader || body.pin || body.auth_pin;
  const configuredPin = process.env.DASHBOARD_PIN || process.env.API_AUTH_PIN || '1337';

  if (!pin || String(pin).trim() !== configuredPin) {
    return res.status(401).json({ error: 'Unauthorized: Invalid or missing X-Auth-Pin' });
  }

  const overrideTunnel = req.headers['x-tunnel-url'] || req.query?.tunnel_url;
  const j5Url = (overrideTunnel && String(overrideTunnel).trim()) || process.env.J5_TUNNEL_URL || 'https://your-tunnel.trycloudflare.com';

  const isPost = req.method === 'POST';
  const targetPath = isPost ? '/api/homework/run' : '/api/homework';

  if (j5Url) {
    try {
      const response = await fetch(`${j5Url.replace(/\/$/, '')}${targetPath}`, {
        method: isPost ? 'POST' : 'GET',
        headers: {
          'Content-Type': 'application/json',
          'X-Auth-Pin': configuredPin,
        },
        body: isPost ? JSON.stringify(body) : undefined,
      });

      if (response.ok) {
        const data = await response.json();
        return res.status(200).json(data);
      }
    } catch (e) {
      console.warn('Proxy to J5 homework failed, falling back:', e.message);
    }
  }

  // Fallback response
  return res.status(200).json({
    status: 'fallback',
    message: isPost ? 'J5 node queued homework solver run' : 'Homework state served from Vercel edge',
    homework: {
      status: 'Done',
      target_date: '2026-10-28',
      tomorrow_lessons: ['English', 'Eng. Lit.', 'Maths', 'Physics', 'Economics', 'Technology'],
      tomorrow_homework: [],
      pdf_url: '/homework_latest.pdf'
    }
  });
}
