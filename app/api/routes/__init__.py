from app.api.routes import jobs, mcp, sessions, utility, workspaces

ROUTERS = [utility.router, workspaces.router, sessions.router, jobs.router, mcp.router]

__all__ = ["ROUTERS"]
