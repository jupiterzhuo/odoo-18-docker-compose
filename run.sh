#!/bin/bash
DESTINATION=$1
PORT=$2
CHAT=$3

# Clone from YOUR Git repository (not a third-party upstream).
# Example: export ODOO_COMPOSE_GIT_URL=https://github.com/YOU/your-odoo-docker-compose.git
if [ -z "${ODOO_COMPOSE_GIT_URL:-}" ]; then
  echo "Error: set ODOO_COMPOSE_GIT_URL to the git URL of this docker-compose project (your own repo)."
  echo "Example: export ODOO_COMPOSE_GIT_URL=https://github.com/YOU/your-odoo-docker-compose.git"
  exit 1
fi

git clone --depth=1 "$ODOO_COMPOSE_GIT_URL" "$DESTINATION"
rm -rf "$DESTINATION/.git"

# Create PostgreSQL directory
mkdir -p $DESTINATION/postgresql

# Change ownership to current user and set restrictive permissions for security
sudo chown -R $USER:$USER $DESTINATION
sudo chmod -R 700 $DESTINATION  # Only the user has access

# Check if running on macOS
if [[ "$OSTYPE" == "darwin"* ]]; then
  echo "Running on macOS. Skipping inotify configuration."
else
  # System configuration
  if grep -qF "fs.inotify.max_user_watches" /etc/sysctl.conf; then
    echo $(grep -F "fs.inotify.max_user_watches" /etc/sysctl.conf)
  else
    echo "fs.inotify.max_user_watches = 524288" | sudo tee -a /etc/sysctl.conf
  fi
  sudo sysctl -p
fi

# Set ports in docker-compose.yml
# Update docker-compose configuration
if [[ "$OSTYPE" == "darwin"* ]]; then
  # macOS sed syntax
  sed -i '' 's/10018/'$PORT'/g' $DESTINATION/docker-compose.yml
  sed -i '' 's/20018/'$CHAT'/g' $DESTINATION/docker-compose.yml
else
  # Linux sed syntax
  sed -i 's/10018/'$PORT'/g' $DESTINATION/docker-compose.yml
  sed -i 's/20018/'$CHAT'/g' $DESTINATION/docker-compose.yml
fi

# Set file and directory permissions after installation
find $DESTINATION -type f -exec chmod 644 {} \;
find $DESTINATION -type d -exec chmod 755 {} \;

chmod +x $DESTINATION/entrypoint.sh

# Run Odoo
if ! is_present="$(type -p "docker-compose")" || [[ -z $is_present ]]; then
  docker compose -f $DESTINATION/docker-compose.yml up -d
else
  docker-compose -f $DESTINATION/docker-compose.yml up -d
fi


echo "Odoo started at http://localhost:$PORT | Master password: see admin_passwd in $DESTINATION/etc/odoo.conf | Live chat port: $CHAT"