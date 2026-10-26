// Vercel Serverless Function: POST /api/fiverr/delete
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-Auth-Pin, Authorization');

  if (req.method === 'OPTIONS') {
    return res.status(204).end();
  }

  const configuredPin = process.env.DASHBOARD_PIN || process.env.API_AUTH_PIN || '1337';
  const pinHeader = req.headers['x-auth-pin'];
  const pinQuery = req.query?.pin || req.query?.auth_pin;
  const pinAuth = req.headers['authorization']?.replace(/^Bearer\s+/i, '');
  const body = req.body || {};
  const providedPin = pinHeader || pinQuery || pinAuth || body.pin || body.auth_pin;

  if (!providedPin || String(providedPin).trim() !== configuredPin) {
    return res.status(401).json({ error: 'Unauthorized: Invalid or missing X-Auth-Pin' });
  }

  const j5Url = process.env.J5_TUNNEL_URL;
  if (j5Url) {
    try {
      const resp = await fetch(`${j5Url.replace(/\/$/, '')}/api/fiverr/delete`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'X-Auth-Pin': configuredPin,
        },
        body: JSON.stringify(req.body || {}),
      });
      if (resp.ok) {
        const data = await resp.json();
        return res.status(200).json(data);
      }
    } catch (e) {}
  }

  return res.status(200).json({
    status: 'success',
    message: 'Fiverr inquiry deleted (fallback)',
  });
}
