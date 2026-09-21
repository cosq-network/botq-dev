FROM alpine:3.20

RUN apk add --no-cache openssh-server git shadow

# Service account used for SSH git access (git-shell-like via login shell).
RUN addgroup -S git 2>/dev/null; \
    adduser -S -D -G git -s /bin/ash -h /home/git git; \
    echo 'git:git' | chpasswd

# Authorized_keys + repo are seeded empty; the deploy public key is appended
# at runtime by the validation driver (mirroring adding a key in GitHub).
RUN install -d -m 700 -o git -g git /home/git/.ssh && \
    install -m 600 -o git -g git /dev/null /home/git/.ssh/authorized_keys

RUN ssh-keygen -A

# Bare "pilot" repository with a single commit on branch main.
RUN git config --global user.email botq@example.com && \
    git config --global user.name botq && \
    git init --bare /srv/git/pilot.git && \
    git --git-dir=/srv/git/pilot.git symbolic-ref HEAD refs/heads/main && \
    cd /tmp && \
    git clone -q /srv/git/pilot.git work && \
    cd work && \
    printf 'pilot seed commit\n' > README.md && \
    git add README.md && \
    git commit -q -m 'initial commit' && \
    git push -q origin HEAD:main && \
    cd / && rm -rf /tmp/work && \
    chown -R git:git /srv/git

RUN mkdir -p /run/sshd

EXPOSE 22

CMD ["/usr/sbin/sshd", "-D", "-e", "-f", "/etc/ssh/sshd_config"]
