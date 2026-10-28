// Vercel Serverless Function: POST /api/bid
export default async function handler(req, res) {
  // CORS
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
  const configuredPin = String(process.env.DASHBOARD_PIN || process.env.API_AUTH_PIN || "1234").trim();

  if (!pin || String(pin).trim() !== configuredPin) {
    return res.status(401).json({ error: 'Unauthorized: Invalid or missing X-Auth-Pin' });
  }

  const { project_id, amount, period = 3, description } = body;

  if (!project_id || !amount || !description) {
    return res.status(400).json({ error: 'Missing required fields: project_id, amount, description' });
  }

  const overrideTunnel = req.headers['x-tunnel-url'] || req.query?.tunnel_url;
  const j5Url = (overrideTunnel && String(overrideTunnel).trim()) || process.env.J5_TUNNEL_URL || 'https://subsequently-skip-breath-pizza.trycloudflare.com';

  // Attempt proxy to J5 tunnel first so state, logs, and matched_jobs.json are synchronized
  if (j5Url) {
    try {
      const j5Resp = await fetch(`${j5Url.replace(/\/$/, '')}/api/bid`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Auth-Pin': configuredPin,
        },
        body: JSON.stringify(body),
      });
      if (j5Resp.ok) {
        const j5Data = await j5Resp.json();
        return res.status(200).json({
          ...j5Data,
          source: 'j5_device_tunnel',
        });
      }
    } catch (e) {
      // fallback to direct Freelancer API submission
    }
  }

  const token = process.env.FREELANCER_OAUTH_TOKEN || '6T7kH6wHALtimwa8xLF4nG55hW9Pz7';
  const userId = process.env.FREELANCER_USER_ID || '94846528';

  const bidPayload = {
    project_id: Number(project_id),
    bidder_id: Number(userId),
    amount: Number(amount),
    period: Number(period),
    milestone_percentage: 100,
    description: String(description).trim(),
  };

  try {
    const flRes = await fetch('https://www.freelancer.com/api/projects/0.1/bids/', {
      method: 'POST',
      headers: {
        'freelancer-oauth-v1': token,
        'Content-Type': 'application/json',
        'User-Agent': 'FreelancerCommandCenter/4.0',
      },
      body: JSON.stringify(bidPayload),
    });

    const data = await flRes.json();

    if (!flRes.ok) {
      return res.status(flRes.status).json({
        error: 'Freelancer API rejected bid',
        code: flRes.status,
        details: data,
      });
    }

    return res.status(200).json({
      status: 'success',
      message: `Bid placed successfully on Project #${project_id}`,
      result: data,
    });
  } catch (err) {
    return res.status(500).json({ error: `Internal bid submission failure: ${err.message}` });
  }
}
