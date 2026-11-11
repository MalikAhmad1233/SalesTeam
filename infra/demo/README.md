# Try Mixt AI (demo)

The whole platform (dashboard, API, background worker and database) started with one command.
**Demo only:** it runs over plain HTTP with no backups. Never enter real customer details.
For a real deployment, use [infra/staging](../staging) and the [operations runbook](../../docs/14-operations-runbook.md).

## Option 1: in your browser, with nothing to install (GitHub Codespaces)

1. On GitHub, open the repository and switch to the branch you want to try.
2. Click **Code**, then **Codespaces**, then **Create codespace on &lt;branch&gt;**.
3. Wait while it sets up. The first time takes 5 to 10 minutes because it builds everything.
4. The dashboard opens in a new browser tab. If it doesn't, open the **Ports** tab and click the
   globe icon next to "Mixt AI dashboard".
5. The sign-in details are printed in the terminal. If you can't see them, open a terminal
   (**Terminal**, then **New Terminal**) and run:

   ```bash
   infra/demo/demo.sh info
   ```

A codespace stops by itself after 30 minutes without use, and it keeps your demo data.
Reopen it from **Code**, then **Codespaces**, and the demo starts again.
Delete the codespace when you're finished, so it doesn't use up your free Codespaces hours.

## Option 2: on your own computer (Kali, Debian, Ubuntu, macOS or Windows with Docker)

From the repository folder, run:

```bash
infra/demo/demo.sh
```

That's it:

* If Docker is missing on Kali, Debian or Ubuntu, the script offers to install it (it asks for your sudo password).
* The first start builds everything (5 to 10 minutes). Later starts take seconds.
* When the demo is ready, the script prints the sign-in details. Then open <http://localhost:3000>.

| To do this | Run |
|---|---|
| Show the address and sign-in again | `infra/demo/demo.sh info` |
| Stop it (data is kept) | `infra/demo/demo.sh stop` |
| Start it again | `infra/demo/demo.sh` |
| Delete the demo and all its data | `infra/demo/demo.sh reset` |
| See what the servers are doing | `infra/demo/demo.sh logs` |

On macOS or Windows, install [Docker Desktop](https://www.docker.com/products/docker-desktop/) first.
On Windows, run the script from WSL or Git Bash.
To use another port, start it with `MIXT_DEMO_PORT=3001 infra/demo/demo.sh`.

## Signing in

* **Email:** `owner@mixt-demo.example`
* **Password:** a random password made for your demo (printed by the script).
* The first sign-in asks you to set up **two-step verification**. Scan the QR code with an
  authenticator app on your phone (Google Authenticator, Microsoft Authenticator, Authy and so on),
  then type the 6-digit code it shows.

The demo starts empty, apart from the 13 supplied price books, which are stored but not active.
You can add leads, customers, tasks, team members and settings to try it out.
WhatsApp and email work only once Mixt's real accounts are connected.
For the demo, connecting them would also need a public HTTPS address, which the demo doesn't have.

## How it works

`demo.sh` writes `infra/demo/.env` the first time. That file holds fresh random database passwords,
an encryption key and the demo password, and it is never committed.

The script then builds the same Docker images as staging and production, and starts them with
[compose.yaml](compose.yaml):

* PostgreSQL with the same three database roles as staging. Only the other containers can reach it.
* The migration job.
* The API, run as the least-privileged database role.
* The background worker.
* The dashboard. Only this one is published, and only on this computer: `127.0.0.1:3000`.

Finally, the script creates the first Owner account.
