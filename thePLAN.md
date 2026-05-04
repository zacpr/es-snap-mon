The PLAN:  To create a pleasant GUI app that tracks the progress of ongoing elasticsearch snapshot backups across multiople clusters and translates the stats for humans

the clsuters etc shoudl be user configuralble but for testing well jsut incldue these 

Clusters:
name: elastic.apac-prod-1.wtg.zone snapsrepo: au2s3-b1.wtg.ws-us2-production policy: slm_apac-prod-1-qid-full-backup-to-s3
name: elastic.amer-prod-1.wtg.zone snapsrepo: us2s3-b1.wtg.ws-us2-production policy: slm_amer-prod-1-qid-full-backup-to-s3
name: elastic.emea-prod-1.wtg.zone snapsrepo: de1s3-b1.wtg.ws-us2-production policy: slm_emea-prod-1-qid-full-backup-to-s3




credentials: provide your own at runtime via the GUI


