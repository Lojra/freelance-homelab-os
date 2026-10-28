// Vercel Serverless Function: POST /api/profile-skills
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
  const configuredPin = String(process.env.DASHBOARD_PIN || process.env.API_AUTH_PIN || "1234").trim();

  if (!pin || String(pin).trim() !== configuredPin) {
    return res.status(401).json({ error: 'Unauthorized: Invalid or missing X-Auth-Pin' });
  }

  const HARDWARE_SKILL_IDS = [43, 76, 111, 265, 394, 440, 612, 630, 1347, 1657];
  const token = process.env.FREELANCER_OAUTH_TOKEN || '6T7kH6wHALtimwa8xLF4nG55hW9Pz7';

  const params = new URLSearchParams();
  for (const sid of HARDWARE_SKILL_IDS) {
    params.append('jobs[]', String(sid));
  }

  try {
    const flRes = await fetch('https://www.freelancer.com/api/users/0.1/self/jobs/', {
      method: 'PUT',
      headers: {
        'freelancer-oauth-v1': token,
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'FreelancerCommandCenter/4.0',
      },
      body: params.toString(),
    });

    const data = await flRes.json();

    if (!flRes.ok) {
      return res.status(flRes.status).json({
        error: 'Failed to sync skills with Freelancer profile',
        details: data,
      });
    }

    return res.status(200).json({
      status: 'success',
      message: 'Hardware skills synced with Freelancer profile',
      skills_count: HARDWARE_SKILL_IDS.length,
      result: data,
    });
  } catch (err) {
    return res.status(500).json({ error: `Internal error updating skills: ${err.message}` });
  }
}
