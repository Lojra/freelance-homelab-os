// Vercel Serverless Function: GET /api/fiverr, POST /api/fiverr/read, DELETE /api/fiverr
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
      let targetPath = '/api/fiverr';
      if (req.method === 'DELETE' && req.query?.id) {
        targetPath += `?id=${encodeURIComponent(req.query.id)}`;
      }
      const resp = await fetch(`${j5Url.replace(/\/$/, '')}${targetPath}`, {
        method: req.method,
        headers: { 
          'Content-Type': 'application/json',
          'X-Auth-Pin': configuredPin,
        },
        body: ['POST', 'PUT'].includes(req.method) ? JSON.stringify(req.body) : undefined,
      });
      if (resp.ok) {
        const data = await resp.json();
        return res.status(200).json(data);
      }
    } catch (e) {}
  }

  // Fallback demo data
  if (req.method === 'DELETE') {
    return res.status(200).json({ status: 'success', message: 'Inquiry removed from inbox (fallback)' });
  }

  return res.status(200).json({
    status: 'success',
    inbox: [
      {
        id: "101",
        sender: "sample_client",
        subject: "New inquiry for PCB enclosure and layout",
        snippet: "Hello! We have an IoT sensor prototype on breadboard and need a clean 2-layer PCB layout with 3D enclosure.",
        timestamp: new Date().toISOString(),
        fiverr_link: "https://www.fiverr.com/inbox",
        status: "unread",
        inquiry_type: "New Message",
      }
    ]
  });
}
