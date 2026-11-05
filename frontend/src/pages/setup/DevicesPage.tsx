import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  devicesApi,
  type DeviceCreateOut,
  type DeviceOut,
} from "../../api/devices";
import { strings } from "../../lib/strings";

export function DevicesPage() {
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [siteId, setSiteId] = useState("");
  const [name, setName] = useState("");
  const [deviceType, setDeviceType] = useState("browser_webcam");
  const [error, setError] = useState<string | null>(null);
  const [createdKey, setCreatedKey] = useState<DeviceCreateOut | null>(null);
  const [rotated, setRotated] = useState<{ id: string; api_key: string } | null>(
    null,
  );

  const list = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });

  const createM = useMutation({
    mutationFn: devicesApi.create,
    onSuccess: (out) => {
      setCreatedKey(out);
      setCreateOpen(false);
      setName("");
      qc.invalidateQueries({ queryKey: ["devices"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const rotateM = useMutation({
    mutationFn: (id: string) => devicesApi.rotateKey(id),
    onSuccess: (out) => {
      setRotated(out);
      qc.invalidateQueries({ queryKey: ["devices"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{strings.devices.title}</Title>
        <Button
          onClick={() => {
            setError(null);
            setCreateOpen(true);
          }}
          data-testid="devices-add"
        >
          {strings.devices.add}
        </Button>
      </Group>
      {error && (
        <Alert color="red" data-testid="devices-error">
          {error}
        </Alert>
      )}
      {createdKey && (
        <Alert
          color="green"
          data-testid="devices-created-key"
          title={strings.devices.keyOnce}
        >
          <Text fw={700} style={{ fontFamily: "monospace" }}>
            {createdKey.api_key}
          </Text>
          <Text size="xs">{strings.devices.keyCopyNow}</Text>
        </Alert>
      )}
      {rotated && (
        <Alert
          color="blue"
          data-testid="devices-rotated-key"
          title={strings.devices.keyRotated}
        >
          <Text fw={700} style={{ fontFamily: "monospace" }}>
            {rotated.api_key}
          </Text>
        </Alert>
      )}
      {list.isLoading ? (
        <Loader />
      ) : list.isError ? (
        <Alert color="red">{strings.devices.loadFailed}</Alert>
      ) : (
        <Table data-testid="devices-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{strings.devices.colName}</Table.Th>
              <Table.Th>{strings.devices.colType}</Table.Th>
              <Table.Th>{strings.devices.colStatus}</Table.Th>
              <Table.Th>{strings.devices.colLastSeen}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(list.data?.items ?? []).map((d: DeviceOut) => (
              <Table.Tr key={d.id}>
                <Table.Td>{d.name}</Table.Td>
                <Table.Td>{d.device_type}</Table.Td>
                <Table.Td>
                  <Badge>{d.status}</Badge>
                </Table.Td>
                <Table.Td>{d.last_seen_at ?? strings.devices.never}</Table.Td>
                <Table.Td>
                  <Button
                    size="xs"
                    variant="light"
                    onClick={() => rotateM.mutate(d.id)}
                  >
                    {strings.devices.rotate}
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Modal
        opened={createOpen}
        onClose={() => setCreateOpen(false)}
        title={strings.devices.addTitle}
      >
        <Stack>
          <TextInput
            label={strings.devices.siteIdLabel}
            value={siteId}
            onChange={(e) => setSiteId(e.currentTarget.value)}
            data-testid="devices-site-id"
          />
          <TextInput
            label={strings.devices.nameLabel}
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            data-testid="devices-name"
          />
          <Select
            label={strings.devices.typeLabel}
            value={deviceType}
            onChange={(v) => setDeviceType(v ?? "browser_webcam")}
            data={["browser_webcam", "kiosk", "mobile"]}
            data-testid="devices-type"
          />
          <Button
            onClick={() => {
              setError(null);
              createM.mutate({
                site_id: siteId,
                name,
                device_type: deviceType,
              });
            }}
            loading={createM.isPending}
            data-testid="devices-create"
          >
            {strings.devices.create}
          </Button>
        </Stack>
      </Modal>
    </Stack>
  );
}
