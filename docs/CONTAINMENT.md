# Legacy containment

The supported application no longer imports or runs the legacy CRA, Express, or
Flask services.

Completed in this worktree:

- Nested `node_modules`, build output, `.env`, model binaries, and runtime caches
  are ignored.
- `client/node_modules`, `server/node_modules`, and `client/build` were removed
  from the Git index with `--cached`; the local generated files were preserved.
- `server/weather/.env` and the obsolete model downloader were removed.
- A content scan found the tracked `WEATHER_API_KEY` value in this checkout is a
  placeholder rather than a live credential.

History rewriting has intentionally not been run automatically. If an
independent full-history secret scan identifies a real credential:

1. Revoke it first at the provider.
2. Freeze merges and create an offline mirror backup.
3. Use `git filter-repo` with exact verified paths/replace rules.
4. Scan every rewritten ref and have a second person verify the result.
5. Coordinate the force-push and require every collaborator to re-clone.

Do not copy an old branch or tag back into the rewritten repository.
