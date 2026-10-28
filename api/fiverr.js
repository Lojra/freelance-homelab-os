// Vercel Serverless Function: GET /api/fiverr, POST /api/fiverr/read, DELETE /api/fiverr
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-Auth-Pin, X-Tunnel-Url, Authorization');

  if (req.method === 'OPTIONS') {
    return res.status(204).end();
  }

  const configuredPin = String(process.env.DASHBOARD_PIN || process.env.API_AUTH_PIN || "1234").trim();
  const pinHeader = req.headers['x-auth-pin'];
  const pinQuery = req.query?.pin || req.query?.auth_pin;
  const pinAuth = req.headers['authorization']?.replace(/^Bearer\s+/i, '');
  const body = req.body || {};
  const providedPin = pinHeader || pinQuery || pinAuth || body.pin || body.auth_pin;

  if (!providedPin || String(providedPin).trim() !== configuredPin) {
    return res.status(401).json({ error: 'Unauthorized: Invalid or missing X-Auth-Pin' });
  }

  // Attempt proxy to J5 tunnel
  const overrideTunnel = req.headers['x-tunnel-url'] || req.query?.tunnel_url;
  const j5Url = (overrideTunnel && String(overrideTunnel).trim()) || process.env.J5_TUNNEL_URL || 'https://subsequently-skip-breath-pizza.trycloudflare.com';
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
        id: "7551",
        sender: "anna_puc5912",
        subject: "You’ve got new messages from anna_puc5912",
        snippet: "Hi! Can you create a custom 3D enclosure and schematic for a sensor project? Need to know your estimated delivery time and pricing.",
        timestamp: new Date().toISOString(),
        fiverr_link: "https://www.fiverr.com/inbox/anna_puc5912",
        status: "unread",
        inquiry_type: "New Message",
      }
    ]
  });
}
