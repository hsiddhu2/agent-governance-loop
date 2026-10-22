from check_outputs import secret_outputs


def template(value) -> dict:
    return {"Outputs": {"Out": {"Value": value}}}


def test_secret_attribute_fails():
    value = {"Fn::GetAtt": ["Client", "UserPoolClient.ClientSecret"]}
    assert secret_outputs(template(value)) == ["Out"]


def test_secret_inside_a_join_fails():
    value = {"Fn::Join": ["", ["x", {"Fn::GetAtt": "Client.ClientSecret"}]]}
    assert secret_outputs(template(value)) == ["Out"]


def test_secret_arn_passes():
    value = {"Fn::GetAtt": ["Provider", "ClientSecretArn.SecretArn"]}
    assert secret_outputs(template(value)) == []


def test_plain_outputs_pass():
    assert secret_outputs(template({"Ref": "Client"})) == []
    assert secret_outputs({}) == []
