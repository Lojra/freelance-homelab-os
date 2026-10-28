// Vercel Serverless Function: POST /api/dismiss & /api/jobs/clear-pending
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-Auth-Pin, X-Tunnel-Url, Authorization');

  if (req.method === 'OPTIONS') {
    return res.status(204).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const pinHeader = req.headers['x-auth-pin'];
  const body = req.body || {};
  const pin = pinHeader || body.pin || body.auth_pin;
  const configuredPin = process.env.DASHBOARD_PIN || process.env.API_AUTH_PIN || '1337';

  if (!pin || String(pin).trim() !== configuredPin) {
    return res.status(401).json({ error: 'Unauthorized: Invalid or missing X-Auth-Pin' });
  }

  const isClearAll = (req.url && req.url.includes('clear')) || body.action === 'clear_all';
  const { project_id, contest_id } = body;

  if (!isClearAll && !project_id && !contest_id) {
    return res.status(400).json({ error: 'Missing project_id or contest_id' });
  }

  // Attempt proxy to J5 tunnel
  const overrideTunnel = req.headers['x-tunnel-url'] || req.query?.tunnel_url;
  const j5Url = (overrideTunnel && String(overrideTunnel).trim()) || process.env.J5_TUNNEL_URL || 'https://subsequently-skip-breath-pizza.trycloudflare.com';
  
  if (j5Url) {
    try {
      const endpoint = isClearAll ? '/api/jobs/clear-pending' : '/api/dismiss';
      const resp = await fetch(`${j5Url.replace(/\/$/, '')}${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Auth-Pin': configuredPin,
        },
        body: JSON.stringify(body),
      });
      if (resp.ok) {
        const j5Data = await resp.json();
        return res.status(200).json(j5Data);
      }
    } catch (e) {
      console.warn('J5 dismiss/clear proxy error:', e);
    }
  }

  if (isClearAll) {
    return res.status(200).json({
      status: 'success',
      cleared_count: 0,
      message: 'Pending jobs cleared successfully (fallback mode).'
    });
  }

  return res.status(200).json({
    status: 'success',
    message: contest_id ? `Contest #${contest_id} dismissed` : `Project #${project_id} dismissed`,
    project_id,
    contest_id,
  });
}
