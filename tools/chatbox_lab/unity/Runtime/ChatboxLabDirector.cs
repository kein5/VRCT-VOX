using UdonSharp;
using UnityEngine;
using VRC.SDKBase;

// Poses the two local test clients for chatbox photos. The first client (the
// instance master) speaks; the other one is the camera. Every `interval`
// seconds the master advances a synced step, and each client moves itself to
// the pose that step defines, so both agree without sending positions.
[UdonBehaviourSyncMode(BehaviourSyncMode.Manual)]
public class ChatboxLabDirector : UdonSharpBehaviour
{
    public Transform[] zones;
    public float interval = 6f;
    public float minDistance = 1.5f;
    public float maxDistance = 7f;
    public float maxAround = 70f;
    public float maxLookOffset = 25f;

    [UdonSynced] private int step;
    private int appliedStep = -1;
    private float nextAdvance;

    private void Start()
    {
        nextAdvance = Time.time + interval;
    }

    private void Update()
    {
        if (Networking.IsMaster && Time.time >= nextAdvance)
        {
            nextAdvance = Time.time + interval;
            step++;
            RequestSerialization();
        }
        if (step != appliedStep) Apply();
    }

    private void Apply()
    {
        VRCPlayerApi local = Networking.LocalPlayer;
        if (local == null || zones == null || zones.Length == 0) return;
        appliedStep = step;
        int zone = (int)(Rand(1) * zones.Length) % zones.Length;
        Vector3 center = zones[zone].position;
        float speakerYaw = Rand(2) * 360f;
        if (local.isMaster)
        {
            local.TeleportTo(center, Quaternion.Euler(0f, speakerYaw, 0f));
            return;
        }
        float distance = Mathf.Lerp(minDistance, maxDistance, Rand(3));
        Quaternion around = Quaternion.Euler(0f, speakerYaw + (Rand(4) * 2f - 1f) * maxAround, 0f);
        Vector3 position = center + around * Vector3.forward * distance;
        Vector3 toSpeaker = center - position;
        toSpeaker.y = 0f;
        Quaternion look = Quaternion.LookRotation(toSpeaker) * Quaternion.Euler(0f, (Rand(5) * 2f - 1f) * maxLookOffset, 0f);
        local.TeleportTo(position, look);
    }

    // Deterministic per step, identical on every client.
    private float Rand(int salt)
    {
        float value = Mathf.Sin(step * 12.9898f + salt * 78.233f) * 43758.5453f;
        return value - Mathf.Floor(value);
    }
}
