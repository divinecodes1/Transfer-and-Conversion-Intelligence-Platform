# Transfer & Conversion Intelligence Platform :: Keycloak, realm included.
#
# Why this image exists at all.
#
# Locally, docker-compose bind-mounts the realm and the themes off the host.
# Azure Container Apps has no equivalent for a single file -- the alternative is
# an Azure Files share, which means a storage mount, an environment-level volume
# definition and a resource that exists solely to deliver two directories that
# never change between deployments. Baking them into the image makes the realm a
# versioned artefact instead: the container that starts in Azure is byte-identical
# to the one that passed CI, and there is no mount to forget.
#
# The realm's redirect URIs are resolved at import time from
# TRANSFEROPS_WEB_ORIGIN, so the same image serves localhost and the deployed
# console without a rebuild.

FROM quay.io/keycloak/keycloak:26.0 AS build

# `kc.sh build` bakes the feature and database choices into the distribution so
# the runtime can start with --optimized, which skips re-deriving all of it on
# every boot. That matters more here than usual: the container scales to zero, so
# start-up happens on a real user's first sign-in and every second is one they
# spend watching a spinner.
#
# It is also a correctness fix, not just a speed one -- `start --optimized`
# against a distribution that was never built fails outright.
ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true

RUN /opt/keycloak/bin/kc.sh build


FROM quay.io/keycloak/keycloak:26.0

COPY --from=build /opt/keycloak/ /opt/keycloak/

# The realm, imported on first start. Import is a no-op once the realm exists,
# so a redeploy does not discard registered users or reset the realm's state.
COPY keycloak/realm-export.json /opt/keycloak/data/import/realm-export.json

# The branded login and email theme. This is the reason the platform runs its
# own identity provider rather than delegating to a tenant login page: the
# registration, verification and recovery flows are part of what it demonstrates.
COPY keycloak/themes/ /opt/keycloak/themes/

ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true

ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start", "--optimized", "--import-realm"]
