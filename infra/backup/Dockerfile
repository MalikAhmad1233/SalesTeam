# Encrypted PostgreSQL backups and restores for Mixt AI (IN-22).
# pg_dump/pg_restore must be at least the server's major version: keep this in step with the database.
FROM postgres:17-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends age \
 && rm -rf /var/lib/apt/lists/*
COPY backup.sh restore.sh /usr/local/bin/
RUN chmod 0755 /usr/local/bin/backup.sh /usr/local/bin/restore.sh \
 && mkdir -p /backups && chown postgres:postgres /backups
USER postgres
ENTRYPOINT []
CMD ["/usr/local/bin/backup.sh", "loop"]
