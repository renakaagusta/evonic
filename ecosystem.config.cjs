module.exports = {
  apps: [
    {
      name: "evonic",
      script: "app.py",
      cwd: __dirname,
      interpreter: __dirname + "/.venv/bin/python",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      restart_delay: 5000,
      kill_timeout: 10000,
      max_restarts: 10,
      min_uptime: "10s",
      out_file: __dirname + "/logs/pm2-out.log",
      error_file: __dirname + "/logs/pm2-error.log",
      merge_logs: true,
      time: true,
      env: {
        PYTHONUNBUFFERED: "1",
      },
    },
  ],
};
