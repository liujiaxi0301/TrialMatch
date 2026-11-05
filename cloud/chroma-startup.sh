#!/usr/bin/env bash
# VM startup script: the database lives on a separate persistent disk.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io curl jq
systemctl enable --now docker
device=/dev/disk/by-id/google-chroma-data
if ! blkid "$device"; then
  mkfs.ext4 -F "$device"
fi
mkdir -p /mnt/chroma
mountpoint -q /mnt/chroma || mount "$device" /mnt/chroma
image=$(curl -fsS -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/attributes/chroma-image)
curl -fsS -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token \
  | jq -r .access_token | docker login -u oauth2accesstoken --password-stdin https://us-east1-docker.pkg.dev
docker pull "$image"
docker rm -f trialmatch-chroma 2>/dev/null || true
docker run -d --name trialmatch-chroma --restart=unless-stopped \
  --memory=1400m -p 8000:8000 -v /mnt/chroma:/data \
  --log-opt max-size=10m --log-opt max-file=3 "$image"
docker logout https://us-east1-docker.pkg.dev
