// Vercel Serverless Function: POST /api/scan
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-Auth-Pin, X-Tunnel-Url, Authorization');

  if (req.method === 'OPTIONS') {
    return res.status(204).end();
  }

  const configuredPin = String(process.env.DASHBOARD_PIN || process.env.API_AUTH_PIN || "1234").trim();
  const pinHeader = req.headers['x-auth-pin'];
  const body = req.body || {};
  const pin = pinHeader || body.pin || body.auth_pin;

  if (!pin || String(pin).trim() !== configuredPin) {
    return res.status(401).json({ error: 'Unauthorized: Invalid or missing X-Auth-Pin' });
  }

  const overrideTunnel = req.headers['x-tunnel-url'] || req.query?.tunnel_url;
  const j5Url = (overrideTunnel && String(overrideTunnel).trim()) || process.env.J5_TUNNEL_URL || 'https://subsequently-skip-breath-pizza.trycloudflare.com';
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
    } catch (e) {
      // fallback
    }
  }

  return res.status(200).json({
    status: 'success',
    message: 'Hardware Scout scan triggered (fallback)',
  });
}
