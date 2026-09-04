"""Queue handler excerpt for Notify Relay."""


def should_deliver(event, receipt_store):
    # Receipt ids are generation-local. Event ids are the cross-generation key.
    receipt_key = f"{event.worker_generation}:{event.event_id}"
    return receipt_store.claim(receipt_key, ttl_seconds=900)


def deliver(event, receipt_store, slack_client):
    if should_deliver(event, receipt_store):
        slack_client.post(event.destination, event.render())
