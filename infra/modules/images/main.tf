# Build e push das imagens dentro do próprio apply (substitui o docker build/push manual).
# A tag é o hash do código: mudou um arquivo, muda a tag, sai imagem nova e
# nova revisão da task definition. Sem mudança no código, nada é refeito.

locals {
  contextos = { for nome, _ in var.repositorios : nome => "${var.diretorio_app}/${nome}" }

  # Arquivos que entram no contexto do build (mesmos ignorados do .dockerignore)
  arquivos = {
    for nome, dir in local.contextos : nome => sort([
      for f in fileset(dir, "**") : f
      if !can(regex("(^|/)(tests|__pycache__|\\.venv|venv|\\.pytest_cache)/|\\.pyc$|(^|/)\\.env", f))
    ])
  }

  # Hash de cada arquivo com fim de linha normalizado (CRLF -> LF): Dockerfile e
  # requirements.txt saem com CRLF no Windows, e a tag tem que ser a mesma em
  # qualquer máquina. (Todos os arquivos do contexto são texto.)
  hash = {
    for nome, dir in local.contextos : nome => sha1(join("", [
      for f in local.arquivos[nome] : "${f}:${sha1(replace(file("${dir}/${f}"), "\r\n", "\n"))}"
    ]))
  }

  tag = { for nome, h in local.hash : nome => substr(h, 0, 12) }
}

resource "docker_image" "this" {
  for_each = var.repositorios

  name         = "${each.value}:${local.tag[each.key]}"
  keep_locally = true # não tenta apagar a imagem local ao trocar de tag

  build {
    context  = local.contextos[each.key]
    platform = var.plataforma
  }

  triggers = {
    hash_codigo = local.hash[each.key]
  }
}

# Push para o ECR (autenticação no provider docker do ambiente)
resource "docker_registry_image" "this" {
  for_each = var.repositorios

  name = docker_image.this[each.key].name

  # Mantém a imagem antiga no ECR ao trocar de tag: um rollback do ECS ainda
  # consegue baixá-la. No destroy, o force_delete do repositório apaga tudo.
  keep_remotely = true

  triggers = {
    hash_codigo = local.hash[each.key]
  }
}
