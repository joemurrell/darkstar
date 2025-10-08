# DarkstarAIC Deployment Examples

This document provides example configurations for deploying DarkstarAIC in different scenarios.

## Environment Variables

### Multi-Server Mode (Recommended)
```bash
# Required
DISCORD_TOKEN=your_discord_bot_token_here
OPENAI_API_KEY=sk-your-openai-key-here

# Optional - leave unset for multi-server mode
# ASSISTANT_ID=
```

### Single-Server Mode (Legacy)
```bash
# Required
DISCORD_TOKEN=your_discord_bot_token_here
OPENAI_API_KEY=sk-your-openai-key-here
ASSISTANT_ID=asst_your_assistant_id_here
```

## Docker Deployment

### Docker Compose (Multi-Server)
```yaml
version: '3.8'

services:
  darkstar:
    build: .
    container_name: darkstar-bot
    restart: unless-stopped
    environment:
      - DISCORD_TOKEN=${DISCORD_TOKEN}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      # ASSISTANT_ID not set = multi-server mode
    volumes:
      - ./logs:/app/logs
```

### Docker Compose (Single-Server)
```yaml
version: '3.8'

services:
  darkstar:
    build: .
    container_name: darkstar-bot
    restart: unless-stopped
    environment:
      - DISCORD_TOKEN=${DISCORD_TOKEN}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ASSISTANT_ID=${ASSISTANT_ID}
    volumes:
      - ./logs:/app/logs
```

## Railway Deployment

Railway configuration is already included in `railway.json`. Simply:

1. Connect your GitHub repository to Railway
2. Add environment variables in Railway dashboard:
   - `DISCORD_TOKEN`
   - `OPENAI_API_KEY`
   - `ASSISTANT_ID` (optional, omit for multi-server)
3. Deploy!

## Kubernetes Deployment

### ConfigMap
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: darkstar-config
data:
  # Add non-sensitive config here if needed
```

### Secret
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: darkstar-secrets
type: Opaque
stringData:
  DISCORD_TOKEN: "your_discord_token"
  OPENAI_API_KEY: "your_openai_key"
  # ASSISTANT_ID: "your_assistant_id"  # Uncomment for single-server mode
```

### Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: darkstar-bot
spec:
  replicas: 1  # Discord bots should only have 1 replica
  selector:
    matchLabels:
      app: darkstar-bot
  template:
    metadata:
      labels:
        app: darkstar-bot
    spec:
      containers:
      - name: darkstar
        image: your-registry/darkstar:latest
        envFrom:
        - secretRef:
            name: darkstar-secrets
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        volumeMounts:
        - name: logs
          mountPath: /app/logs
      volumes:
      - name: logs
        emptyDir: {}
```

## Production Database Integration

For production deployments, replace the in-memory `GUILD_ASSISTANTS` dictionary with database storage.

### PostgreSQL Example
```python
import psycopg2

# In your initialization code
conn = psycopg2.connect(
    host="your-db-host",
    database="darkstar",
    user="darkstar_user",
    password="your-password"
)

# Create table
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS guild_assistants (
        guild_id BIGINT PRIMARY KEY,
        assistant_id TEXT NOT NULL,
        vector_store_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")
conn.commit()

# Load assistants on startup
async def load_guild_assistants():
    cursor = conn.cursor()
    cursor.execute("SELECT guild_id, assistant_id, vector_store_id FROM guild_assistants")
    for row in cursor.fetchall():
        GUILD_ASSISTANTS[row[0]] = {
            "assistant_id": row[1],
            "vector_store_id": row[2]
        }
    logger.info(f"Loaded {len(GUILD_ASSISTANTS)} guild assistants from database")

# Save assistant after creation
async def save_guild_assistant(guild_id, assistant_id, vector_store_id):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO guild_assistants (guild_id, assistant_id, vector_store_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (guild_id) 
        DO UPDATE SET 
            assistant_id = EXCLUDED.assistant_id,
            vector_store_id = EXCLUDED.vector_store_id,
            updated_at = CURRENT_TIMESTAMP
    """, (guild_id, assistant_id, vector_store_id))
    conn.commit()
    
    # Also update in-memory cache
    GUILD_ASSISTANTS[guild_id] = {
        "assistant_id": assistant_id,
        "vector_store_id": vector_store_id
    }
```

### MongoDB Example
```python
from motor.motor_asyncio import AsyncIOMotorClient

# In your initialization code
mongo_client = AsyncIOMotorClient("mongodb://localhost:27017")
db = mongo_client.darkstar
guild_assistants_collection = db.guild_assistants

# Load assistants on startup
async def load_guild_assistants():
    async for doc in guild_assistants_collection.find():
        GUILD_ASSISTANTS[doc['guild_id']] = {
            "assistant_id": doc['assistant_id'],
            "vector_store_id": doc.get('vector_store_id')
        }
    logger.info(f"Loaded {len(GUILD_ASSISTANTS)} guild assistants from MongoDB")

# Save assistant after creation
async def save_guild_assistant(guild_id, assistant_id, vector_store_id):
    await guild_assistants_collection.update_one(
        {'guild_id': guild_id},
        {
            '$set': {
                'assistant_id': assistant_id,
                'vector_store_id': vector_store_id,
                'updated_at': datetime.utcnow()
            },
            '$setOnInsert': {
                'created_at': datetime.utcnow()
            }
        },
        upsert=True
    )
    
    # Also update in-memory cache
    GUILD_ASSISTANTS[guild_id] = {
        "assistant_id": assistant_id,
        "vector_store_id": vector_store_id
    }
```

## Monitoring and Logging

### Structured Logging
The bot already uses structured logging. For production, consider:

1. **Log aggregation**: Send logs to Datadog, Splunk, or ELK stack
2. **Metrics**: Track API usage, response times, error rates
3. **Alerts**: Set up alerts for errors and API failures

### Example with Datadog
```python
from datadog import initialize, statsd

# Initialize Datadog
initialize(
    api_key=os.environ.get('DATADOG_API_KEY'),
    app_key=os.environ.get('DATADOG_APP_KEY')
)

# Track metrics
@statsd.timed('darkstar.ask_command.duration')
async def ask_command(interaction, question):
    statsd.increment('darkstar.ask_command.count')
    # ... rest of command
```

## Cost Optimization

### Multi-Server Mode Costs
- **Assistant creation**: Free
- **Vector stores**: $0.10/GB/day
- **API usage**: ~$0.01-0.05 per quiz or Q&A session

### Tips to Reduce Costs
1. Monitor inactive servers and clean up unused assistants
2. Set document upload size limits
3. Implement rate limiting on quiz generation
4. Use shorter timeout values for API calls
5. Consider caching frequently asked questions

### Cost Monitoring Script
```python
async def calculate_monthly_cost():
    """Estimate monthly OpenAI costs"""
    total_size_gb = 0
    
    for guild_id, data in GUILD_ASSISTANTS.items():
        vector_store_id = data.get('vector_store_id')
        if vector_store_id:
            # Get vector store size
            vs = oai.beta.vector_stores.retrieve(vector_store_id)
            size_gb = vs.usage_bytes / (1024**3)
            total_size_gb += size_gb
    
    monthly_storage_cost = total_size_gb * 0.10 * 30
    logger.info(f"Estimated monthly storage cost: ${monthly_storage_cost:.2f}")
    return monthly_storage_cost
```

## High Availability Setup

For mission-critical deployments:

1. **Database replication**: Use PostgreSQL streaming replication or MongoDB replica sets
2. **Load balancing**: Not applicable for Discord bots (must be single instance)
3. **Failover**: Use Kubernetes with health checks and automatic restarts
4. **Backup**: Regular backups of database and assistant configurations

### Health Check Endpoint
Add a simple health check:
```python
from aiohttp import web

async def health_check(request):
    # Check bot connection
    if not client.is_ready():
        return web.Response(status=503, text="Bot not ready")
    
    # Check OpenAI connection
    try:
        oai.models.list()
    except Exception:
        return web.Response(status=503, text="OpenAI connection failed")
    
    return web.Response(status=200, text="OK")

# Start health check server
app = web.Application()
app.router.add_get('/health', health_check)
runner = web.AppRunner(app)
await runner.setup()
site = web.TCPSite(runner, '0.0.0.0', 8080)
await site.start()
```

## Security Best Practices

1. **Environment variables**: Never commit secrets to git
2. **Bot permissions**: Use least privilege principle
3. **Rate limiting**: Implement rate limits for commands
4. **Input validation**: Already implemented for file uploads
5. **Admin-only commands**: Already restricted with `@app_commands.default_permissions(administrator=True)`
6. **API key rotation**: Regularly rotate OpenAI API keys
7. **Audit logging**: Log all admin actions (setup, upload, delete)

## Scaling Considerations

Current architecture limitations:
- Single bot instance (Discord requirement)
- In-memory state (needs database for persistence)
- No horizontal scaling (Discord bots can't be load balanced)

For large deployments (100+ servers):
- Use database for persistence
- Implement assistant pooling or sharing
- Consider separate bot instances for different server groups
- Monitor and optimize OpenAI API usage
