# Run the medical assistance demo locally

This is a simulation. It does not call, text or email medical services. For an actual emergency, contact campus medical services or local emergency services directly.

With Docker Desktop running, open PowerShell in the project folder and start a temporary local database:

```powershell
docker run --rm --name campus-medical-local-db -p 127.0.0.1:18099:8000 amazon/dynamodb-local:latest -jar DynamoDBLocal.jar -inMemory -sharedDb
```

Keep that window open. In a second PowerShell window in the same folder, install the project dependencies if needed, then run:

```powershell
.\.venv\Scripts\python.exe -m scripts.local_demo
```

On first launch, choose an email and password for the **local demo admin**. Open [the local demo](http://127.0.0.1:8000/?api_url=http://127.0.0.1:8000), create a guest request, and sign in as that admin to simulate the response. The launcher uses fictional contacts, fake AWS credentials, a loopback database endpoint, and simulated notifications. It does not modify your AWS profile.

The database command above keeps data in memory: stopping its window deletes its local demo data. Keep it running while restarting the application if you want to retain the local records. The application creates a new signing secret each time it starts, so admin sessions must sign in again and retries of an old alert submission should not be reused after a restart. No AWS resources or existing project database are deleted by this setup.
