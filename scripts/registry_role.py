"""Create the registry's service-linked role if the account does not have it yet.

The registry uses this role to encrypt and decrypt records with the catalog's key, and
the key policy names it. KMS rejects a key policy that names a role that does not
exist, and in this account the registry did not create the role itself, so it is created
here before the registry stack is deployed. One role per account. It is left in place
by `make destroy`: other registries in the account may use it.
"""
import boto3

ROLE = "AWSServiceRoleForAgentRegistry"
SERVICE = "agent-registry.amazonaws.com"


def main() -> None:
    iam = boto3.client("iam")
    try:
        iam.get_role(RoleName=ROLE)
        print(f"{ROLE}: present")
    except iam.exceptions.NoSuchEntityException:
        iam.create_service_linked_role(AWSServiceName=SERVICE)
        print(f"{ROLE}: created")


if __name__ == "__main__":
    main()
