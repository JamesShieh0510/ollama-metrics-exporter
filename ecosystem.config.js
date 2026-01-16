// PM2 配置文件
// 使用方法: pm2 start ecosystem.config.js

module.exports = {
  apps: [
    {
      name: 'ollama-gateway',
      script: 'src/ollama_gateway.py',
      interpreter: 'python3',
      cwd: '/Users/jamesshieh/projects/ollama-metrics-exporter',
      watch: ['src', 'config'],
      ignore_watch: ['__pycache__', '*.log', 'data', 'backups', 'docs'],
      autorestart: true,
      env: {
        GATEWAY_PORT: '11435',
        SCHEDULING_STRATEGY: 'round_robin',
        // 配置文件路径（可选，默认使用 config/node_config.json）
        // NODE_CONFIG_FILE: 'config/node_config.json'
      },
      error_file: './logs/gateway-error.log',
      out_file: './logs/gateway-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
    },
    {
      name: 'ollama-exporter',
      script: 'src/ollama_exporter.py',
      interpreter: 'python3',
      cwd: '/Users/jamesshieh/projects/ollama-metrics-exporter',
      watch: ['src'],
      ignore_watch: ['__pycache__', '*.log', 'data', 'backups', 'docs'],
      autorestart: true,
      env: {
        NODE_NAME: 'node1',
        OLLAMA_PORT: '11434',
      },
      error_file: './logs/exporter-error.log',
      out_file: './logs/exporter-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
    }
  ]
};
