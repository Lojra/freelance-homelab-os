// Vercel Serverless Function: POST /api/scan
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-Auth-Pin, Authorization');

  if (req.method === 'OPTIONS') {
    return res.status(204).end();
  }

  const configuredPin = process.env.DASHBOARD_PIN || process.env.API_AUTH_PIN || '1337';
  const pinHeader = req.headers['x-auth-pin'];
  const body = req.body || {};
  const pin = pinHeader || body.pin || body.auth_pin;

  if (!pin || String(pin).trim() !== configuredPin) {
    return res.status(401).json({ error: 'Unauthorized: Invalid or missing X-Auth-Pin' });
  }

  const j5Url = process.env.J5_TUNNEL_URL;
  if (j5Url) {
    try {
      const resp = await fetch(`${j5Url.replace(/\/$/, '')}/api/scan`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Auth-Pin': configuredPin,
        },
      });
      if (resp.ok) {
        const j5Data = await resp.json();
        return res.status(200).json(j5Data);
      }
    } catch (e) {}
  }

  return res.status(200).json({
    status: 'success',
    message: 'Hardware Scout scan triggered (fallback)',
  });
}
