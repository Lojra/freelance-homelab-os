// Vercel Serverless Function: GET /api/jobs
import stateHandler from './state.js';

export default async function handler(req, res) {
  // Leverage stateHandler to get standardized job queue
  const mockRes = {
    statusCode: 200,
    headers: {},
    setHeader(k, v) { this.headers[k] = v; res.setHeader(k, v); },
    status(code) { this.statusCode = code; res.status(code); return this; },
    json(data) {
      if (this.statusCode >= 400) return res.json(data);
      return res.status(200).json({
        status: 'success',
        jobs: data.jobs || [],
        count: (data.jobs || []).length,
        source: data.source,
      });
    },
    end() { res.end(); }
  };

  return stateHandler(req, mockRes);
}
