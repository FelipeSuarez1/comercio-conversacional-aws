# Bootstrap do state remoto

Cria o bucket S3 que guarda o state do Terraform de `envs/sa-east-1`
(versionado, criptografado, sem acesso público). O state deste diretório
fica **local** e é aplicado **uma vez só** por conta/região.

```bash
cd infra/bootstrap
terraform init
terraform apply            # região padrão: sa-east-1 (mude com -var regiao=...)
terraform output -raw bucket_nome
```

Copie o nome do bucket para `infra/envs/sa-east-1/backend.hcl`
(a partir de `backend.hcl.example`) e siga para o `init` do ambiente.

O bucket tem `force_destroy = false`: para apagá-lo é preciso esvaziá-lo
(inclusive as versões) antes. Não apague o `terraform.tfstate` local deste
diretório enquanto o bucket existir.
