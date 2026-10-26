// Vercel Serverless Function: POST /api/bid
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-Auth-Pin, Authorization');

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

  const { project_id, amount, period = 3, description } = body;

  if (!project_id || !amount || !description) {
    return res.status(400).json({ error: 'Missing required fields: project_id, amount, description' });
  }

  const token = process.env.FREELANCER_OAUTH_TOKEN;
  const userId = process.env.FREELANCER_USER_ID;

  if (!token || !userId) {
    return res.status(500).json({ error: 'FREELANCER_OAUTH_TOKEN and FREELANCER_USER_ID environment variables must be configured' });
  }

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
        'User-Agent': 'HomelabCommandCenter/1.0',
      },
      body: JSON.stringify(bidPayload),
    });

    const data = await flRes.json();

    if (!flRes.ok) {
      return res.status(flRes.status).json({
        error: 'Freelancer API rejected bid',
        details: data,
      });
    }

    return res.status(200).json({
      status: 'success',
      message: `Bid placed successfully on Project #${project_id}`,
      result: data,
    });
  } catch (err) {
    return res.status(500).json({ error: `Internal error placing bid: ${err.message}` });
  }
}
