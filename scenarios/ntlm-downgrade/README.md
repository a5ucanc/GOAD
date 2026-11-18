# ntlm-downgrade

DC accepts LM and NTLMv1 (LmCompatibilityLevel 2). Sets `ntlm.lmcompat` to `2` on a domain controller (default: the root DC).

Attack:

Coerce the DC with Responder set to a fixed challenge and crack or convert the NTLMv1 response:

    responder -I <iface> --lm
    # coerce the DC (printerbug / PetitPotam), then crack.sh or ntlmv1-multi

How to verify:

    reg query HKLM\SYSTEM\CurrentControlSet\Control\Lsa /v LmCompatibilityLevel   # 0x2 when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
